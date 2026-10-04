from fastapi import APIRouter

from api.account import router as account_router
from api.archive import router as archive_router
from api.commands import router as commands_router
from api.emoji_status import router as emoji_status_router
from api.locale import router as locale_router
from api.mirror import router as mirror_router
from api.settings import router as settings_router


def setup_routers() -> APIRouter:
    router = APIRouter()
    router.include_router(commands_router)
    router.include_router(settings_router)
    router.include_router(emoji_status_router)
    router.include_router(locale_router)
    router.include_router(account_router)
    router.include_router(mirror_router)
    router.include_router(archive_router)
    return router
