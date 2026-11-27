from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from app.features.ai.bot import router as ai_drafts_router
from app.features.alerts.bot import router as alerts_router
from app.features.archive.bot import router as archive_router
from app.features.connection.bot import router as connection_router
from app.features.games.bot import router as games_router
from app.features.history.outgoing import install_outgoing_recorder
from app.features.linkscan.bot import router as linkscan_router
from app.features.mirror.bot import router as mirror_router
from app.features.ops.bot import router as ops_router
from app.features.ops.middleware import OpsContextMiddleware
from app.features.settings.bot import router as settings_router
from app.features.ui_stickers.bot import router as ui_stickers_router
from app.features.userbot.bot import router as userbot_router
from app.platform.telegram.dm import router as bot_commands_router
from app.platform.telegram.middleware import UpdateLoggingMiddleware
from app.platform.telegram.pipeline import router as business_messages_router
from app.platform.telegram.self_actions import install_edit_marker
from config import settings

# разметку указываем явно (parse_mode="html") там, где она есть; превью ссылок выключены
# глобально, где оно нужно — LinkPreviewOptions(is_disabled=False)
bot = Bot(
    token=settings.BOT_TOKEN,
    default=DefaultBotProperties(link_preview_is_disabled=True),
)
install_edit_marker(bot)
install_outgoing_recorder(bot)
dp = Dispatcher(storage=MemoryStorage())


def setup_routes() -> Dispatcher:
    dp.update.outer_middleware(OpsContextMiddleware("bot"))
    dp.update.outer_middleware(UpdateLoggingMiddleware())

    dp.include_router(connection_router)
    dp.include_router(business_messages_router)
    dp.include_router(
        linkscan_router
    )  # до архива: смотрит правки, ничего не перехватывая
    dp.include_router(archive_router)
    dp.include_router(alerts_router)
    dp.include_router(ops_router)
    dp.include_router(mirror_router)
    dp.include_router(games_router)
    dp.include_router(settings_router)
    dp.include_router(userbot_router)
    dp.include_router(ui_stickers_router)
    dp.include_router(ai_drafts_router)
    dp.include_router(bot_commands_router)  # последним: см. docstring модуля

    return dp
