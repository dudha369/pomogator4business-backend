import hashlib
import hmac
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from core import database as db
from core.crypto import decrypt_token
from mirror.router import router as mirror_router
from core.utils import log_suppressed

logger = logging.getLogger("bot.mirror")

# Один общий диспетчер на ВСЕ зеркала разом — компилируется один раз, а не
# по разу на владельца, как было при отдельном Dispatcher на start_polling().
mirror_dispatcher = Dispatcher(storage=MemoryStorage())
mirror_dispatcher.include_router(mirror_router)


def _derive_mirror_secret(bot_token: str) -> str:
    digest = hashlib.sha256(f"pomogator4business-mirror-webhook:{bot_token}".encode())
    return digest.hexdigest()


def _mirror_webhook_url(owner_id: int) -> str:
    return f"{settings.WEBHOOK_BASE_URL}{settings.MIRROR_WEBHOOK_PATH}/{owner_id}"


class MirrorStartError(Exception):
    """Зеркало не запустилось. code: "no_webhook_url" | "webhook_failed"."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class MirrorManager:
    """Один лёгкий Bot (HTTP-клиент на aiohttp, без фонового long-polling
    цикла) на каждого владельца с активным зеркалом. Апдейты приходят через
    вебхук на наш же FastAPI и ОБЩИЙ Dispatcher — в отличие от прежней
    реализации на start_polling(), здесь не держится ни одной долгоживущей
    задачи и ни одного постоянно открытого long-poll соединения. Именно они
    были главным подозреваемым по росту потребления памяти при увеличении
    числа подключённых зеркал (и, вероятно, причиной самопроизвольных
    падений процесса на Free-плане Render)."""

    def __init__(self):
        self._bots: dict[int, Bot] = {}
        self._secrets: dict[int, str] = {}

    def is_running(self, owner_id):
        return owner_id in self._bots

    def get_bot(self, owner_id):
        return self._bots.get(owner_id)

    def verify_secret(self, owner_id, secret_token):
        expected = self._secrets.get(owner_id)
        return (
            expected is not None
            and secret_token is not None
            and hmac.compare_digest(secret_token, expected)
        )

    async def start_mirror(self, owner_id, token, *, drop_pending=False):
        """Запускает зеркало; при неудаче бросает MirrorStartError (никакого
        молчаливого return). Новый токен заменяет старый, но только после того,
        как вебхук нового бота успешно установлен — иначе остаётся рабочий старый.

        drop_pending=True — только для свежего подключения: на деплое очередь
        трогать нельзя, там лежат ещё не обработанные сообщения."""
        secret = _derive_mirror_secret(token)
        if self._secrets.get(owner_id) == secret:
            return  # то же зеркало уже запущено — идемпотентно

        if not settings.WEBHOOK_BASE_URL:
            logger.warning(
                "WEBHOOK_BASE_URL не задан — зеркало owner_id=%s не запущено", owner_id
            )
            raise MirrorStartError("no_webhook_url")

        bot = Bot(token=token)
        try:
            await bot.set_webhook(
                url=_mirror_webhook_url(owner_id),
                secret_token=secret,
                drop_pending_updates=drop_pending,
                allowed_updates=["message", "my_chat_member"],
            )
        except Exception as exc:
            logger.exception(
                "Не удалось установить вебхук зеркала owner_id=%s", owner_id
            )
            try:
                await bot.session.close()
            except Exception:
                log_suppressed("core/mirror_manager.py:86", benign=True)
            raise MirrorStartError("webhook_failed") from exc

        previous = self._bots.get(owner_id)
        self._bots[owner_id] = bot
        self._secrets[owner_id] = secret
        if previous:  # старый токен больше не должен принимать апдейты
            await self._shutdown_bot(previous, delete_webhook=True)

    @staticmethod
    async def _shutdown_bot(bot, *, delete_webhook):
        if delete_webhook:
            try:
                await bot.delete_webhook()
            except Exception:
                log_suppressed("core/mirror_manager.py:101", benign=True)
        try:
            await bot.session.close()
        except Exception:
            log_suppressed("core/mirror_manager.py:105", benign=True)

    async def stop_mirror(self, owner_id):
        bot = self._bots.pop(owner_id, None)
        self._secrets.pop(owner_id, None)
        if bot:
            await self._shutdown_bot(bot, delete_webhook=True)

    async def start_all(self):
        mirrors = await db.get_all_active_mirrors()
        for row in mirrors:
            # Одно битое зеркало (например, после смены BOT_TOKEN токен уже
            # не расшифровывается) не должно валить запуск всего приложения.
            try:
                token = decrypt_token(row["token_encrypted"])
                await self.start_mirror(row["owner_id"], token)
            except Exception:
                logger.exception(
                    "Не удалось запустить зеркало owner_id=%s", row["owner_id"]
                )

    async def stop_all(self):
        """Закрывает только локальные HTTP-сессии — вебхуки на стороне
        Telegram НЕ отключаем: на редеплое новый процесс просто
        переустановит те же URL (идемпотентно), а явная отписка здесь
        значит каждый редеплой на несколько секунд "глушил" бы зеркала."""
        for owner_id in list(self._bots.keys()):
            bot = self._bots.pop(owner_id, None)
            self._secrets.pop(owner_id, None)
            if bot:
                try:
                    await bot.session.close()
                except Exception:
                    log_suppressed("core/mirror_manager.py:132", benign=True)


mirror_manager = MirrorManager()
