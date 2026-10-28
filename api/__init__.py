from fastapi import APIRouter

from api.locale import router as locale_router
from api.mirror import router as mirror_router
from api.emoji_status import router as emoji_status_router
from api.autoresponder import router as autoresponder_router
from api.commands import router as commands_router
from api.settings import router as settings_router
from api.account import router as account_router
from api.archive import router as archive_router
from api.avatar import router as avatar_router
from api.chat_info import router as chat_info_router
from api.aliases import router as aliases_router
from api.stats import router as stats_router
from api.favorites import router as favorites_router
from api.chats import router as chats_router
from api.ping import router as ping_router
from api.archive_export import router as archive_export_router
from api.templates import router as templates_router
from api.chat_flags import router as chat_flags_router
from api.ai import router as ai_router
from api.reminders import router as reminders_router
from api.backup import router as backup_router


def setup_routers() -> APIRouter:
    router = APIRouter()

    router.include_router(locale_router)
    router.include_router(mirror_router)
    router.include_router(emoji_status_router)
    router.include_router(autoresponder_router)
    router.include_router(commands_router)
    router.include_router(settings_router)
    router.include_router(account_router)
    router.include_router(archive_router)
    router.include_router(avatar_router)
    router.include_router(chat_info_router)
    router.include_router(aliases_router)
    router.include_router(stats_router)
    router.include_router(favorites_router)
    router.include_router(chats_router)
    router.include_router(ping_router)
    router.include_router(archive_export_router)
    router.include_router(templates_router)
    router.include_router(chat_flags_router)
    router.include_router(ai_router)
    router.include_router(reminders_router)
    router.include_router(backup_router)

    return router
