import hashlib
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from core import database as db
from core.crypto import decrypt_token
from mirror.router import router as mirror_router

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
        return expected is not None and secret_token == expected

    async def start_mirror(self, owner_id, token):
        if owner_id in self._bots:
            return

        if not settings.WEBHOOK_BASE_URL:
            logger.warning(
                "WEBHOOK_BASE_URL не задан — зеркало owner_id=%s не может "
                "быть запущено", owner_id,
            )
            return

        bot = Bot(token=token)
        secret = _derive_mirror_secret(token)

        try:
            await bot.set_webhook(
                url=_mirror_webhook_url(owner_id),
                secret_token=secret,
                drop_pending_updates=True,
                allowed_updates=["message", "my_chat_member"],
            )
        except Exception:
            logger.exception(
                "Не удалось установить вебхук зеркала owner_id=%s", owner_id
            )
            try:
                await bot.session.close()
            except Exception:
                pass
            return

        self._bots[owner_id] = bot
        self._secrets[owner_id] = secret

    async def stop_mirror(self, owner_id):
        bot = self._bots.pop(owner_id, None)
        self._secrets.pop(owner_id, None)
        if not bot:
            return

        try:
            await bot.delete_webhook()
        except Exception:
            pass
        try:
            await bot.session.close()
        except Exception:
            pass

    async def start_all(self):
        mirrors = await db.get_all_active_mirrors()
        for row in mirrors:
            token = decrypt_token(row["token_encrypted"])
            await self.start_mirror(row["owner_id"], token)

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
                    pass


mirror_manager = MirrorManager()
