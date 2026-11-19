from aiogram import Router

from app.features.mirror.mirror_bot.blocked import router as blocked_router
from app.features.mirror.mirror_bot.spam import router as spam_router

router = Router(name="mirror_root")
router.include_router(spam_router)
router.include_router(blocked_router)
