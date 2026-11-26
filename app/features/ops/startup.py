"""Проверка при старте. Блокирующие (БД, версия миграций, vault) срывают запуск:
Render оставит прежнюю версию, а администраторы получат причину. Остальное (вебхук,
юзербот, env) — итоговое сообщение «сборка / миграция / проверки» чуть позже."""

import asyncio
import logging
import re
import time

from tortoise import Tortoise

from app.features.ops import scrub
from config import ROOT_DIR, settings

logger = logging.getLogger("bot.ops")

MIGRATIONS_DIR = ROOT_DIR / "db" / "migrations" / "models"
_NUMBER = re.compile(r"^(\d+)_")
_REPORT_DELAY = 15  # даём вебхуку и менеджеру юзербота отработать


class StartupError(Exception):
    """Запуск небезопасен: данные важнее работы бота."""


class DbUnavailable(StartupError):
    pass


class MigrationMismatch(StartupError):
    def __init__(self, db: int | None, repo: int):
        super().__init__(f"БД: {db}, репозиторий: {repo}")
        self.db, self.repo = db, repo


def repo_version() -> int:
    numbers = [
        int(m.group(1))
        for p in MIGRATIONS_DIR.glob("*.py")
        if (m := _NUMBER.match(p.name))
    ]
    return max(numbers, default=0)


async def db_version() -> int | None:
    """Номер последней применённой миграции; None — таблицы aerich нет или она пуста."""
    conn = Tortoise.get_connection("default")
    try:
        rows = await conn.execute_query_dict(
            "SELECT version FROM aerich WHERE app = 'models' ORDER BY id DESC LIMIT 1"
        )
    except Exception:
        return None
    m = _NUMBER.match(rows[0]["version"]) if rows else None
    return int(m.group(1)) if m else None


async def check_db() -> int:
    """Миллисекунды ответа БД; недоступна — DbUnavailable."""
    started = time.monotonic()
    try:
        await asyncio.wait_for(
            Tortoise.get_connection("default").execute_query("SELECT 1"), 5
        )
    except Exception as exc:
        raise DbUnavailable(type(exc).__name__) from exc
    return int((time.monotonic() - started) * 1000)


async def check_migrations() -> None:
    """БД старше И новее кода — отказ: откат кода на схему из будущего тоже рискован."""
    if settings.SKIP_MIGRATION_CHECK:
        logger.warning("SKIP_MIGRATION_CHECK: версия миграций НЕ проверяется")
        return
    db, repo = await db_version(), repo_version()
    if db != repo:
        raise MigrationMismatch(db, repo)


async def check_fatal() -> None:
    await check_db()
    await check_migrations()


def _render_failure(exc: BaseException, stage: str):
    from app.features.ops.notify import esc
    from app.platform.i18n import t

    d = scrub.describe(exc)

    def render(locale: str):
        if isinstance(exc, MigrationMismatch):
            text = t(
                "ops.start.migration",
                locale,
                db=exc.db if exc.db is not None else "—",
                repo=exc.repo,
                build=esc(settings.BUILD),
            )
        elif stage == "vault":
            text = t(
                "ops.start.vault",
                locale,
                reason=esc(scrub.scrub_text(str(exc))[:200]),
                build=esc(settings.BUILD),
            )
        elif stage == "db" or isinstance(exc, DbUnavailable):
            text = t(
                "ops.start.db", locale, kind=esc(d.kind), build=esc(settings.BUILD)
            )
        else:
            text = t(
                "ops.start.unknown",
                locale,
                kind=esc(d.kind),
                place=esc(d.place),
                build=esc(settings.BUILD),
            )
        return text, None

    return render


async def announce_failure(exc: BaseException, *, stage: str = "startup") -> None:
    """Сообщить администраторам причину отказа напрямую через Bot API (БД может быть
    недоступна). Не бросает и не задерживает отказ дольше 10 секунд."""
    from app.features.ops import notify

    try:
        await asyncio.wait_for(
            notify.send_to_admins(_render_failure(exc, stage)), timeout=10
        )
    except Exception:
        logger.warning("Не удалось сообщить администраторам об отказе запуска")


async def report_started(delay: float = _REPORT_DELAY) -> None:
    """Итог запуска: одно сообщение. Всё зелёное — без звука."""
    from app.features.ops import health, notify

    await asyncio.sleep(delay)
    try:
        report = await health.collect()
        silent = report.status == "ok"
        await notify.send_to_admins(
            lambda locale: (health.render_text(report, locale, started=True), None),
            silent=silent,
        )
    except Exception:
        logger.exception("Итог запуска не сформирован")
