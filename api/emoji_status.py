"""Часы в эмодзи-статусе: чтение состояния, сохранение разрешения
(requestEmojiStatusAccess на фронте не сохраняется само — см. AccountPage
фронтенда), переключение вкл/выкл."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from core import database as db
from core.clock_styles import CLOCK_PACK_COUNT, CLOCK_STYLES, is_valid_clock_style
from core.utils import log_suppressed

router = APIRouter()


async def build_styles_payload():
    ready = await db.get_completed_clock_styles(CLOCK_PACK_COUNT)
    return [
        {"id": style.id, "titles": style.titles, "available": style.id in ready}
        for style in CLOCK_STYLES
    ]


@router.get("/emoji-status")
async def get_emoji_status(user: dict = Depends(require_user)):
    return {
        "granted": await db.is_emoji_status_granted(user["id"]),
        "enabled": await db.is_emoji_status_enabled(user["id"]),
        "style": await db.get_emoji_status_style(user["id"]),
        "styles": await build_styles_payload(),
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
        "style": await db.get_emoji_status_style(owner_id),
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


class EmojiStatusStyle(BaseModel):
    style: str


@router.post("/settings/emoji-status/style")
async def set_emoji_status_style(
    payload: EmojiStatusStyle, user: dict = Depends(require_user)
):
    owner_id = user["id"]
    if not is_valid_clock_style(payload.style):
        raise HTTPException(status_code=400, detail="Unknown clock style")

    ready = await db.get_completed_clock_styles(CLOCK_PACK_COUNT)
    if payload.style not in ready:
        raise HTTPException(status_code=400, detail="Clock style is not available yet")

    await db.set_emoji_status_style(owner_id, payload.style)

    if await db.is_emoji_status_enabled(owner_id) and await db.is_emoji_status_granted(
        owner_id
    ):
        from bot_instance import bot
        from core.scheduler import refresh_emoji_status

        try:
            await refresh_emoji_status(bot, owner_id)
        except Exception:
            log_suppressed("api/emoji_status.py:style")

    return {"style": payload.style}
