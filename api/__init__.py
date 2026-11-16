from fastapi import APIRouter

from api.locale import router as locale_router
from api.mirror import router as mirror_router
from api.emoji_status import router as emoji_status_router
from api.autoresponder import router as autoresponder_router
from api.commands import router as commands_router
from api.settings import router as settings_router
from api.account import router as account_router
from api.avatar import router as avatar_router
from api.chat_info import router as chat_info_router
from api.aliases import router as aliases_router
from api.stats import router as stats_router
from api.favorites import router as favorites_router
from api.chats import router as chats_router
from api.ping import router as ping_router
from api.chat_flags import router as chat_flags_router
from api.ai import router as ai_router
from api.backup import router as backup_router
from app.features import FEATURES, feature_module

# общие эндпоинты (пока не переехали в фичи); порядок сохранён
_COMMON = (
    locale_router,
    mirror_router,
    emoji_status_router,
    autoresponder_router,
    commands_router,
    settings_router,
    account_router,
    avatar_router,
    chat_info_router,
    aliases_router,
    stats_router,
    favorites_router,
    chats_router,
    ping_router,
    chat_flags_router,
    ai_router,
    backup_router,
)


def setup_routers() -> APIRouter:
    router = APIRouter()
    for common in _COMMON:
        router.include_router(common)
    # REST фич: `app/features/<f>/api.py` с `router` (необязательно)
    for feature in FEATURES:
        module = feature_module(feature, "api")
        if module:
            router.include_router(module.router)
    return router
