"""Часы в эмодзи-статусе: чтение состояния, сохранение разрешения
(requestEmojiStatusAccess на фронте не сохраняется само — см. AccountPage
фронтенда), переключение вкл/выкл."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.features.alerts import service as alerts_service
from app.features.emoji_clock import STYLES, is_valid_style_id
from app.features.emoji_clock import queries as status_db
from app.features.emoji_clock.queries import get_clock_emojis_at, get_clock_pack_counts
from app.features.emoji_clock.style import local_time_key
from app.platform.api.deps import require_user
from app.platform.api.schemas import EmojiStatusState
from app.platform.utils import log_suppressed
from db.models.user_locale import get_timezone_offset

router = APIRouter()


class EmojiStatusFlags(BaseModel):
    granted: bool
    enabled: bool
    style: str


class EmojiEnabledOut(BaseModel):
    enabled: bool


class EmojiStyleOut(BaseModel):
    style: str


async def build_styles_payload(owner_id: int | None = None) -> list[dict]:
    """Список стилей для выбора. available=False — паки стиля ещё не загружены.

    С owner_id у каждого стиля есть `preview_emoji_id`: эмодзи текущей минуты в часовом
    поясе владельца (живое превью). Без owner_id превью не считается."""
    ready = await get_clock_pack_counts()
    previews = {}
    if owner_id is not None:
        time_key = local_time_key(
            datetime.now(UTC), await get_timezone_offset(owner_id)
        )
        previews = await get_clock_emojis_at(time_key)
    return [
        {
            "id": style.id,
            "titles": style.titles,
            "available": ready.get(style.id, 0) >= style.pack_count,
            "preview_emoji_id": previews.get(style.id),
        }
        for style in STYLES
    ]


@router.get("/emoji-status", response_model=EmojiStatusState)
async def get_emoji_status(user: dict = Depends(require_user)):
    return {
        "granted": await status_db.is_emoji_status_granted(user["id"]),
        "enabled": await status_db.is_emoji_status_enabled(user["id"]),
        "style": await status_db.get_emoji_status_style(user["id"]),
        "styles": await build_styles_payload(user["id"]),
    }


class EmojiStatusGrant(BaseModel):
    granted: bool


@router.post("/emoji-status/grant", response_model=EmojiStatusFlags)
async def grant_emoji_status(
    payload: EmojiStatusGrant, user: dict = Depends(require_user)
):
    owner_id = user["id"]
    await status_db.set_emoji_status_granted(owner_id, payload.granted)
    if payload.granted:
        await status_db.set_emoji_status_enabled(owner_id, True)
        await alerts_service.resolve(owner_id, "emoji_access_revoked")

    return {
        "granted": await status_db.is_emoji_status_granted(owner_id),
        "enabled": await status_db.is_emoji_status_enabled(owner_id),
        "style": await status_db.get_emoji_status_style(owner_id),
    }


class EmojiStatusToggle(BaseModel):
    enabled: bool


@router.post("/settings/emoji-status", response_model=EmojiEnabledOut)
async def toggle_emoji_status(
    payload: EmojiStatusToggle, user: dict = Depends(require_user)
):
    if not await status_db.is_emoji_status_granted(user["id"]):
        raise HTTPException(status_code=400, detail="Access not granted yet")

    await status_db.set_emoji_status_enabled(user["id"], payload.enabled)

    if not payload.enabled:
        from bot_instance import bot

        try:
            await bot.set_user_emoji_status(
                user_id=user["id"], emoji_status_custom_emoji_id=""
            )
        except Exception:
            log_suppressed("app/features/emoji_clock/api.py:61")

    return {"enabled": payload.enabled}


class EmojiStatusStyle(BaseModel):
    style: str


@router.post("/settings/emoji-status/style", response_model=EmojiStyleOut)
async def set_emoji_status_style(
    payload: EmojiStatusStyle, user: dict = Depends(require_user)
):
    """Выбор вида часов. Применяется сразу, если часы уже включены."""
    owner_id = user["id"]
    if not is_valid_style_id(payload.style):
        raise HTTPException(status_code=400, detail="Unknown clock style")

    available = {
        item["id"] for item in await build_styles_payload() if item["available"]
    }
    if payload.style not in available:
        raise HTTPException(status_code=400, detail="Clock style is not available yet")

    await status_db.set_emoji_status_style(owner_id, payload.style)

    if await status_db.is_emoji_status_enabled(
        owner_id
    ) and await status_db.is_emoji_status_granted(owner_id):
        from app.features.emoji_clock.bot import refresh_emoji_status
        from bot_instance import bot

        try:
            await refresh_emoji_status(bot, owner_id)
        except Exception:
            log_suppressed("app/features/emoji_clock/api.py:style")

    return {"style": payload.style}
