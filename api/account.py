"""Сводка для вкладки "Аккаунт" мини-приложения: подключение, зеркало,
эмодзи-статус, часовой пояс."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from api.emoji_status import build_styles_payload
from core import database as db
from db.models.user_locale import is_valid_timezone

router = APIRouter()


@router.get("/account")
async def get_account(user: dict = Depends(require_user)):
    owner_id = user["id"]
    connection = await db.get_connection_by_owner(owner_id)

    connection_info = None
    if connection:
        try:
            rights = (
                json.loads(connection["rights_json"])
                if connection.get("rights_json")
                else {}
            )
        except (json.JSONDecodeError, TypeError):
            rights = {}

        connection_info = {
            "owner_name": connection.get("owner_name"),
            "owner_username": connection.get("owner_username"),
            "prefix": connection["prefix"],
            "rights": rights,
        }

    mirror = await db.get_mirror(owner_id)
    mirror_info = {
        "connected": bool(mirror and mirror["is_active"]),
        "username": mirror["bot_username"] if mirror else None,
    }

    return {
        "connection": connection_info,
        "mirror": mirror_info,
        "emoji_status": {
            "granted": await db.is_emoji_status_granted(owner_id),
            "enabled": await db.is_emoji_status_enabled(owner_id),
            "style": await db.get_emoji_status_style(owner_id),
            "styles": await build_styles_payload(),
        },
        "timezone_offset_minutes": await db.get_timezone_offset(owner_id),
        "timezone": await db.get_timezone_name(owner_id),
    }


class TimezoneUpdate(BaseModel):
    # IANA-имя (Intl.DateTimeFormat().resolvedOptions().timeZone) — предпочтительно:
    # учитывает летнее время. Фиксированное смещение — для ручного выбора из списка.
    timezone: str | None = None
    offset_minutes: int | None = None


@router.post("/account/timezone")
async def update_timezone(payload: TimezoneUpdate, user: dict = Depends(require_user)):
    owner_id = user["id"]
    if payload.timezone is not None:
        if not is_valid_timezone(payload.timezone):
            raise HTTPException(status_code=400, detail="Invalid timezone")
        await db.set_timezone_name(owner_id, payload.timezone)
    elif payload.offset_minutes is not None:
        if not -720 <= payload.offset_minutes <= 840:
            raise HTTPException(status_code=400, detail="Invalid timezone offset")
        await db.set_timezone_offset(owner_id, payload.offset_minutes)
    else:
        raise HTTPException(
            status_code=422, detail="timezone or offset_minutes required"
        )
    return {
        "offset_minutes": await db.get_timezone_offset(owner_id),
        "timezone": await db.get_timezone_name(owner_id),
    }
