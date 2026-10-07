# api/avatar.py — новый файл
"""Прокси для аватарок собеседников в веб-аппе — отдаёт байты картинки, а не
file_id (который требует токен бота и не может быть использован напрямую
с фронтенда). Доступ ограничен: можно запросить только аватарку того,
кто реально писал этому владельцу (известный чат), а не произвольный
Telegram user_id — иначе это была бы открытая прокси-дыра для слежки."""

from fastapi import APIRouter, Depends, HTTPException, Response

from api.deps import require_user
from core import database as db
from core.media import download_user_avatar

router = APIRouter()


@router.get("/avatar/{target_user_id}")
async def get_avatar(target_user_id: int, user: dict = Depends(require_user)):
    is_known = await db.is_known_chat(user["id"], target_user_id)
    if not is_known:
        raise HTTPException(status_code=404, detail="Unknown chat")

    from bot_instance import bot

    avatar_bytes = await download_user_avatar(bot, target_user_id)
    if not avatar_bytes:
        raise HTTPException(status_code=404, detail="No avatar")

    return Response(
        content=avatar_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=3600"},
    )
