"""REST чатов: аватары, карточка собеседника, избранное, список/прочтение, флаги чата."""

from fastapi import APIRouter

from app.features.chats.api import avatar, chats, favorites, flags, info

router = APIRouter()
for _module in (avatar, info, favorites, chats, flags):
    router.include_router(_module.router)
