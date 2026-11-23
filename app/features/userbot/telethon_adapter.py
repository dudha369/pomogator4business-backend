"""ЕДИНСТВЕННОЕ место (вместе с telethon_snapshot.py), где импортируется Telethon.

Остальной код видит только `QrLoginGateway`, `RunningClient` и исключения из errors.py;
смена библиотеки (Kurigram) = переписать эти файлы. Строка сессии наружу выходит только
через `session_string()` и в логи не попадает."""

import logging

from telethon import TelegramClient, errors
from telethon.sessions import StringSession

from app.features.userbot.errors import (
    FloodWait,
    PasswordInvalid,
    PasswordNeeded,
    SessionRevoked,
)
from config import settings

logger = logging.getLogger("bot.userbot.telethon")

# в «Устройствах» Telegram сеанс называется так
_DEVICE = "Помогатор"

_REVOKED = (
    errors.AuthKeyUnregisteredError,
    errors.AuthKeyDuplicatedError,
    errors.SessionRevokedError,
    errors.SessionExpiredError,
    errors.UserDeactivatedError,
    errors.UserDeactivatedBanError,
)


def new_client(session: str = "") -> TelegramClient:
    return TelegramClient(
        StringSession(session or None),
        settings.TELEGRAM_API_ID,
        settings.TELEGRAM_API_HASH,
        device_model=_DEVICE,
        system_version="server",
        app_version="1.0",
        connection_retries=5,
        retry_delay=2,
        auto_reconnect=True,
    )


def translate(exc: BaseException) -> BaseException:
    """Ошибка Telethon -> исключение слоя. Прочие возвращаются как есть."""
    if isinstance(exc, _REVOKED):
        return SessionRevoked(type(exc).__name__)
    if isinstance(exc, errors.SessionPasswordNeededError):
        return PasswordNeeded()
    if isinstance(exc, errors.PasswordHashInvalidError):
        return PasswordInvalid()
    if isinstance(exc, errors.FloodWaitError):
        return FloodWait(int(exc.seconds))
    return exc


class QrLoginGateway:
    """Вход по QR. Клиент временный (пустая сессия), живёт только на время входа."""

    def __init__(self):
        self._client = new_client()
        self._qr = None

    async def start(self) -> str:
        try:
            await self._client.connect()
            self._qr = await self._client.qr_login()
        except Exception as exc:
            raise translate(exc) from exc
        return self._qr.url

    async def wait(self, within: float) -> bool:
        """True — QR принят и вход завершён; False — токен истёк, нужен новый."""
        try:
            await self._qr.wait(within)
        except TimeoutError:
            return False
        except Exception as exc:
            raise translate(exc) from exc
        return True

    async def recreate(self) -> str:
        try:
            await self._qr.recreate()
        except Exception as exc:
            raise translate(exc) from exc
        return self._qr.url

    async def password(self, password: str) -> None:
        try:
            await self._client.sign_in(password=password)
        except Exception as exc:
            raise translate(exc) from exc

    async def identity(self) -> tuple[int, str | None]:
        me = await self._client.get_me()
        return me.id, me.username

    def session_string(self) -> str:
        return self._client.session.save()

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:
            logger.debug("disconnect временного клиента не удался", exc_info=True)


class RunningClient:
    """Рабочий клиент владельца: подключение, проверка сессии, остановка, выход."""

    def __init__(self, session: str):
        self._initial = session
        self._client = new_client(session)

    async def connect(self) -> tuple[int, str | None]:
        """Подключается и проверяет, что сессия жива. SessionRevoked — если нет."""
        try:
            await self._client.connect()
            if not await self._client.is_user_authorized():
                raise SessionRevoked("unauthorized")
            me = await self._client.get_me()
        except Exception as exc:
            await self.close()
            raise translate(exc) from exc
        return me.id, me.username

    async def wait_disconnected(self) -> None:
        """Возвращается, когда Telethon окончательно потерял связь (после его повторов)."""
        await self._client.disconnected

    def session_string(self) -> str:
        return self._client.session.save()

    def session_changed(self) -> bool:
        return self.session_string() != self._initial

    @property
    def client(self) -> TelegramClient:
        return self._client

    async def log_out(self) -> bool:
        """Завершить сеанс на стороне Telegram: строка сессии становится мёртвой."""
        try:
            return bool(await self._client.log_out())
        except Exception as exc:
            if isinstance(translate(exc), SessionRevoked):
                return True  # уже завершён
            logger.warning("log_out не удался (%s)", type(exc).__name__)
            return False

    async def close(self) -> None:
        try:
            await self._client.disconnect()
        except Exception:
            logger.debug("disconnect не удался", exc_info=True)
