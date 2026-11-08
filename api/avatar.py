"""Прокси для аватарок собеседников в веб-аппе — отдаёт байты картинки, а не
file_id (который требует токен бота и не может быть использован напрямую
с фронтенда). Доступ ограничен: можно запросить только аватарку того,
кто реально писал этому владельцу (известный чат), а не произвольный
Telegram user_id — иначе это была бы открытая прокси-дыра для слежки."""

import time

from fastapi import APIRouter, Depends, HTTPException, Response

from api.deps import require_user
from core import database as db
from core.media import download_user_avatar

router = APIRouter()

# Аватарки и «аватарки нет» кэшируем в памяти: карточки архива просят одну и ту же
# картинку десятки раз, и каждый раз ходить за ней в Telegram незачем.
_TTL_FOUND = 3600
_TTL_MISSING = 600
_MAX_ENTRIES = 500
_cache: dict[int, tuple[float, bytes | None]] = {}


def _cached(user_id):
    hit = _cache.get(user_id)
    if hit and hit[0] > time.monotonic():
        return True, hit[1]
    return False, None


def _remember(user_id, data):
    if len(_cache) >= _MAX_ENTRIES:
        _cache.clear()  # простая защита от разрастания
    ttl = _TTL_FOUND if data else _TTL_MISSING
    _cache[user_id] = (time.monotonic() + ttl, data)


@router.get("/avatar/{target_user_id}")
async def get_avatar(target_user_id: int, user: dict = Depends(require_user)):
    is_known = await db.is_known_chat(user["id"], target_user_id)
    if not is_known:
        raise HTTPException(status_code=404, detail="Unknown chat")

    from bot_instance import bot

    hit, avatar_bytes = _cached(target_user_id)
    if not hit:
        avatar_bytes = await download_user_avatar(bot, target_user_id)
        _remember(target_user_id, avatar_bytes)
    if not avatar_bytes:
        raise HTTPException(status_code=404, detail="No avatar")

    return Response(
        content=avatar_bytes,
        media_type="image/jpeg",
        headers={"Cache-Control": "private, max-age=3600"},
    )
