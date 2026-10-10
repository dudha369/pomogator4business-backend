"""Часы в эмодзи-статусе: чтение состояния, сохранение разрешения
(requestEmojiStatusAccess на фронте не сохраняется само — см. AccountPage
фронтенда), переключение вкл/выкл."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from core import database as db
from core.utils import log_suppressed

router = APIRouter()


@router.get("/emoji-status")
async def get_emoji_status(user: dict = Depends(require_user)):
    return {
        "granted": await db.is_emoji_status_granted(user["id"]),
        "enabled": await db.is_emoji_status_enabled(user["id"]),
    }


class EmojiStatusGrant(BaseModel):
    granted: bool


@router.post("/emoji-status/grant")
async def grant_emoji_status(
    payload: EmojiStatusGrant, user: dict = Depends(require_user)
):
    owner_id = user["id"]
    await db.set_emoji_status_granted(owner_id, payload.granted)
    if payload.granted:
        await db.set_emoji_status_enabled(owner_id, True)

    return {
        "granted": await db.is_emoji_status_granted(owner_id),
        "enabled": await db.is_emoji_status_enabled(owner_id),
    }


class EmojiStatusToggle(BaseModel):
    enabled: bool


@router.post("/settings/emoji-status")
async def toggle_emoji_status(
    payload: EmojiStatusToggle, user: dict = Depends(require_user)
):
    if not await db.is_emoji_status_granted(user["id"]):
        raise HTTPException(status_code=400, detail="Access not granted yet")

    await db.set_emoji_status_enabled(user["id"], payload.enabled)

    if not payload.enabled:
        from bot_instance import bot

        try:
            await bot.set_user_emoji_status(
                user_id=user["id"], emoji_status_custom_emoji_id=""
            )
        except Exception:
            log_suppressed("api/emoji_status.py:61")

    return {"enabled": payload.enabled}
