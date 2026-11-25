"""ЕДИНСТВЕННОЕ место (вместе с telethon_snapshot.py), где импортируется Telethon.

Остальной код видит только `QrLoginGateway`, `RunningClient` и исключения из errors.py;
смена библиотеки (Kurigram) = переписать эти файлы. Строка сессии наружу выходит только
через `session_string()` и в логи не попадает."""

import logging

from telethon import TelegramClient, errors, events
from telethon.sessions import StringSession

from app.features.userbot import telethon_snapshot as snapshots
from app.features.userbot.errors import (
    FloodWait,
    PasswordInvalid,
    PasswordNeeded,
    SessionRevoked,
)
from app.features.userbot.ub_types import UbDialog
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

    # --- события ---------------------------------------------------------------

    async def listen(self, sink) -> None:
        """Подписывается на новые, изменённые и удалённые сообщения.

        `sink` (events.UserbotSink): `wants(chat_id, kind)` — ранний фильтр по правилам
        (выключенные чаты не стоят ничего), `new/edited(UbMessage)`, `deleted(chat_id, ids)`.
        Сбой обработчика одного события не должен ронять клиента."""
        client = self._client

        async def build(event):
            message = event.message
            guess = "private" if event.is_private else "group"
            if not await sink.wants(event.chat_id, guess):
                return None
            chat = await event.get_chat()
            try:
                sender = await message.get_sender()
            except Exception:
                sender = None  # имя автора — украшение, не повод терять сообщение

            def download():
                return client.download_media(message, file=bytes)

            return snapshots.ub_message(message, chat, sender, download)

        def safe(handler, make):
            async def run(event):
                try:
                    arg = await make(event)
                    if arg is not None:
                        await handler(arg)
                except Exception as exc:
                    logger.warning("Обработчик события: %s", type(exc).__name__)
                    logger.debug("детали сбоя обработчика", exc_info=True)

            return run

        client.add_event_handler(safe(sink.new, build), events.NewMessage())
        client.add_event_handler(safe(sink.edited, build), events.MessageEdited())

        async def on_deleted(event):
            try:
                await sink.deleted(event.chat_id, list(event.deleted_ids))
            except Exception as exc:
                logger.warning("Обработчик удаления: %s", type(exc).__name__)
                logger.debug("детали сбоя обработчика", exc_info=True)

        client.add_event_handler(on_deleted, events.MessageDeleted())

    async def list_dialogs(self, limit: int) -> list[UbDialog]:
        """Диалоги аккаунта (в т.ч. из папок и архива) — для экрана выбора чатов.
        Заодно наполняет кэш сущностей Telethon: без него обновления каналов не идут."""
        out = []
        async for dialog in self._client.iter_dialogs(limit=limit):
            entity = dialog.entity
            if getattr(entity, "is_self", False) or dialog.id == 777000:
                continue  # «Избранное» и служебный чат Telegram
            out.append(
                UbDialog(
                    id=dialog.id,
                    kind=snapshots.chat_kind(entity),
                    title=dialog.name or "",
                    username=getattr(entity, "username", None),
                    members=getattr(entity, "participants_count", None),
                    archived=bool(getattr(dialog, "archived", False)),
                    is_bot=bool(getattr(entity, "bot", False)),
                )
            )
        return out

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
