"""Приёмник ошибок: logging.Handler (ERROR + exc_info) → память → пачкой в БД.

Один приёмник вместо правки сотен `except`: aiogram (его пишет UpdateLoggingMiddleware),
FastAPI (uvicorn и наш обработчик 500), spawn и циклы (`logger.exception`), asyncio
(«Task exception was never retrieved») — всё идёт через logging. `log_suppressed`
(WARNING) сюда не попадает: это ожидаемые сбои. Одно и то же исключение, залогированное
дважды (middleware + вебхук), считается один раз — метка на самом объекте."""

import asyncio
import contextlib
import logging
import threading
import time

from app.features.ops import scrub, service
from app.platform import log_context

logger = logging.getLogger("bot.ops")  # свой логгер приёмник игнорирует (нет петли)

FLUSH_INTERVAL = 2
MAX_PENDING = 500
_DB_NOTICE_EVERY = 600

_BY_LOGGER = (
    ("bot.userbot", "userbot"),
    ("bot.vault", "vault"),
    ("bot.mirror", "mirror"),
    ("bot.retention", "task"),
    ("bot.webhook", "bot"),
    ("bot.updates", "bot"),
    ("uvicorn", "api"),
)

_pending: dict[str, service.Item] = {}
_lock = threading.Lock()
_last_db_notice = 0.0


def component_for(logger_name: str) -> str:
    comp = log_context.current().get("comp")
    if comp:
        return str(comp)
    for prefix, name in _BY_LOGGER:
        if logger_name.startswith(prefix):
            return name
    return "app"


def push(exc: BaseException, component: str) -> None:
    d = scrub.describe(exc)
    kind_full = f"{type(exc).__module__}.{type(exc).__qualname__}"
    fp = scrub.fingerprint(component, kind_full, d.fingerprint_key)
    with _lock:
        item = _pending.get(fp)
        if item:
            item.n += 1
            item.place, item.sample = d.place, d.sample
        elif len(_pending) < MAX_PENDING:
            _pending[fp] = service.Item(
                fp,
                component,
                d.kind,
                d.place,
                1 if d.critical else 0,
                d.sample,
            )


class OpsHandler(logging.Handler):
    def __init__(self):
        super().__init__(logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            exc = record.exc_info[1] if record.exc_info else None
            if exc is None or record.name.startswith("bot.ops"):
                return
            if getattr(exc, "_ops_seen", False):
                return
            with contextlib.suppress(Exception):  # объект без атрибутов: считаем дважды
                exc._ops_seen = True
            push(exc, component_for(record.name))
        except Exception:
            pass


_handler: OpsHandler | None = None


def install() -> None:
    """Подключает приёмник к корневому логгеру (повторный вызов безвреден)."""
    global _handler
    root = logging.getLogger()
    if _handler is None:
        _handler = OpsHandler()
    if _handler not in root.handlers:  # basicConfig(force=True) мог его снять
        root.addHandler(_handler)


def uninstall() -> None:
    global _handler
    if _handler is not None:
        logging.getLogger().removeHandler(_handler)
        _handler = None


def drain() -> list[service.Item]:
    with _lock:
        items = list(_pending.values())
        _pending.clear()
    return items


def _requeue(items: list[service.Item]) -> None:
    with _lock:
        for it in items:
            mine = _pending.get(it.fingerprint)
            if mine:
                mine.n += it.n
            elif len(_pending) < MAX_PENDING:
                _pending[it.fingerprint] = it


async def flush_once(now: int | None = None) -> int:
    """Пишет накопленное и оповещает. Возвращает число обработанных отпечатков."""
    global _last_db_notice
    from app.features.ops import notify

    items = drain()
    if not items:
        return 0
    now = int(now if now is not None else time.time())
    try:
        decisions = await service.process(items, now)
    except Exception:
        logger.warning("Журнал ошибок: БД недоступна, события отложены", exc_info=False)
        _requeue(items)
        if time.time() - _last_db_notice > _DB_NOTICE_EVERY:
            _last_db_notice = time.time()
            await notify.db_unreachable()
        return 0
    burst = service.throttle.add_events(sum(i.n for i in items), now)
    await notify.dispatch(decisions, burst, now)
    return len(items)


async def run_writer() -> None:
    while True:
        await asyncio.sleep(FLUSH_INTERVAL)
        try:
            await flush_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Сбой записи журнала ошибок", exc_info=False)
