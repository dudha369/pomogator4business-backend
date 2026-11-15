from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import settings
from app.platform.telegram.middleware import UpdateLoggingMiddleware
from core.self_actions import install_edit_marker
from handlers.connection import router as connection_router
from handlers.business_messages import router as business_messages_router
from commands.archive import router as archive_router
from handlers.mirror import router as mirror_router
from app.features.games.bot import router as games_router
from handlers.settings import router as settings_router
from handlers.ai_drafts import router as ai_drafts_router
from handlers.bot_commands import router as bot_commands_router

# разметку указываем явно (parse_mode="html") там, где она есть; превью ссылок выключены
# глобально, где оно нужно — LinkPreviewOptions(is_disabled=False)
bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(link_preview_is_disabled=True),
)
install_edit_marker(bot)
dp = Dispatcher(storage=MemoryStorage())


def setup_routes() -> Dispatcher:
    dp.update.outer_middleware(UpdateLoggingMiddleware())

    dp.include_router(connection_router)
    dp.include_router(business_messages_router)
    dp.include_router(archive_router)
    dp.include_router(mirror_router)
    dp.include_router(games_router)
    dp.include_router(settings_router)
    dp.include_router(ai_drafts_router)
    dp.include_router(bot_commands_router)  # последним: см. docstring модуля

    return dp
