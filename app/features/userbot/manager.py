"""Жизненный цикл клиентов юзербота. Без aiogram.

Одна фоновая задача на процесс: берёт advisory lock, затем сверяет БД и работающие
клиенты (reconcile). БД — шина команд: API только пишет статус (`removing`, новая
сессия), а запуск, остановку и `log_out` выполняет процесс, держащий блокировку. Так
сессия никогда не работает в двух процессах сразу.

Потеряна блокировка — все клиенты останавливаются немедленно; затем попытки взять её
снова. Сбой клиента — перезапуск с экспоненциальной паузой."""

import asyncio
import contextlib
import logging
import time

from app.features.userbot import queries
from app.features.userbot.errors import SessionRevoked
from app.features.userbot.lock import make_lock
from app.platform.tasks import spawn
from config import settings

logger = logging.getLogger("bot.userbot")

LOCK_RETRY = 15  # пауза между попытками взять блокировку
TICK = 10  # период сверки и heartbeat
BACKOFF_MIN, BACKOFF_MAX = 5, 300
ALERT_AFTER_FAILURES = 3  # столько подряд неудач — предупреждение владельцу


class _Slot:
    """Запущенный клиент одного владельца."""

    def __init__(self, owner_id: int, client):
        self.owner_id = owner_id
        self.client = client
        self.watch: asyncio.Task | None = None


class UserbotManager:
    def __init__(self, client_factory=None, lock_factory=make_lock):
        self._client_factory = client_factory or _default_client
        self._lock_factory = lock_factory
        self.slots: dict[int, _Slot] = {}
        self._failures: dict[int, int] = {}
        self._next_try: dict[int, float] = {}
        self._wake = asyncio.Event()
        self.holds_lock = False

    # --- публичное ---------------------------------------------------------------

    def is_running(self, owner_id: int) -> bool:
        return owner_id in self.slots

    def nudge(self) -> None:
        """Сверить БД сейчас, а не через TICK."""
        self._wake.set()

    async def run(self) -> None:
        if not settings.USERBOT_CONFIGURED:
            logger.info("Юзербот выключен: TELEGRAM_API_ID/HASH не заданы")
            return
        while True:
            lock = self._lock_factory()
            try:
                if not await lock.acquire():
                    await asyncio.sleep(LOCK_RETRY)
                    continue
                self.holds_lock = True
                logger.info("Блокировка юзербота получена")
                await self._serve(lock)
            except asyncio.CancelledError:
                await self.stop_all()
                raise
            except Exception:
                logger.exception("Цикл юзербота упал")
            finally:
                self.holds_lock = False
                await self.stop_all()
                await lock.release()
            await asyncio.sleep(LOCK_RETRY)

    async def stop_all(self) -> None:
        for owner_id in list(self.slots):
            await self._stop(owner_id)

    # --- цикл --------------------------------------------------------------------

    async def _serve(self, lock) -> None:
        while True:
            if not await lock.check():
                logger.warning("Блокировка юзербота потеряна: клиенты остановлены")
                return
            await self.reconcile()
            self._wake.clear()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._wake.wait(), timeout=TICK)

    async def reconcile(self) -> None:
        wanted = set(await queries.owners_with_status("active"))
        for owner_id in await queries.owners_with_status("removing"):
            await self._remove(owner_id)
            wanted.discard(owner_id)
        for owner_id in list(self.slots):
            if owner_id not in wanted:
                await self._stop(owner_id)
        for owner_id in wanted - set(self.slots):
            if time.monotonic() >= self._next_try.get(owner_id, 0):
                await self._start(owner_id)

    # --- один клиент -------------------------------------------------------------

    async def _start(self, owner_id: int) -> None:
        session = await queries.get_session_string(owner_id)
        if session is None:
            await self._failed(owner_id, "no_session")
            return
        client = self._client_factory(session)
        try:
            user_id, _ = await client.connect()
        except SessionRevoked:
            await self._revoked(owner_id)
            return
        except Exception as exc:
            await self._failed(owner_id, type(exc).__name__)
            return
        info = await queries.get_info(owner_id)
        if info and info["tg_user_id"] not in (None, user_id):
            await client.close()
            await self._revoked(owner_id)  # в строке сессия чужого аккаунта
            return
        slot = _Slot(owner_id, client)
        slot.watch = spawn(self._watch(slot), name=f"userbot-watch-{owner_id}")
        self.slots[owner_id] = slot
        self._failures.pop(owner_id, None)
        await queries.set_connected(owner_id, True)
        logger.info("Юзербот %s подключён", owner_id)

    async def _watch(self, slot: _Slot) -> None:
        """Telethon сам переподключается; сюда доходит окончательная потеря связи."""
        try:
            await slot.client.wait_disconnected()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Юзербот %s: ошибка связи (%s)", slot.owner_id, type(exc).__name__
            )
        if self.slots.get(slot.owner_id) is slot:
            self.slots.pop(slot.owner_id, None)
            await self._failed(slot.owner_id, "disconnected")
            self.nudge()

    async def _stop(self, owner_id: int) -> None:
        slot = self.slots.pop(owner_id, None)
        if slot is None:
            return
        if slot.watch:
            slot.watch.cancel()
        try:
            if slot.client.session_changed():  # смена DC: сохраняем новую строку
                await queries.update_session_string(
                    owner_id, slot.client.session_string()
                )
        except Exception:
            logger.warning("Не удалось сохранить обновлённую сессию %s", owner_id)
        await slot.client.close()

    async def _remove(self, owner_id: int) -> None:
        """Владелец отключил юзербота: завершаем сеанс в Telegram и стираем строку."""
        await self._stop(owner_id)
        session = await queries.get_session_string(owner_id)
        if session:
            client = self._client_factory(session)
            try:
                await client.connect()
                await client.log_out()
            except Exception as exc:
                logger.info("log_out %s не выполнен (%s)", owner_id, type(exc).__name__)
            finally:
                await client.close()
        await queries.delete_session(owner_id)
        self._failures.pop(owner_id, None)
        self._next_try.pop(owner_id, None)

    async def _revoked(self, owner_id: int) -> None:
        await queries.set_status(owner_id, "revoked", error="revoked")
        self._failures.pop(owner_id, None)
        await _report(owner_id, "userbot_session_revoked")

    async def _failed(self, owner_id: int, error: str) -> None:
        count = self._failures.get(owner_id, 0) + 1
        self._failures[owner_id] = count
        delay = min(BACKOFF_MAX, BACKOFF_MIN * 2 ** (count - 1))
        self._next_try[owner_id] = time.monotonic() + delay
        await queries.set_connected(owner_id, False, error[:64])
        logger.warning(
            "Юзербот %s: сбой #%s (%s), повтор через %sс", owner_id, count, error, delay
        )
        if count == ALERT_AFTER_FAILURES:
            await _report(owner_id, "userbot_disconnected")


def _default_client(session: str):
    from app.features.userbot.telethon_adapter import RunningClient

    return RunningClient(session)


async def _report(owner_id: int, code: str) -> None:
    from app.features.alerts.bot import report

    await report(owner_id, code)


manager = UserbotManager()
