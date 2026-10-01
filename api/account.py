"""Сводка для вкладки "Аккаунт" мини-приложения: подключение, зеркало,
эмодзи-статус, часовой пояс."""

import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from core import database as db

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
        },
        "timezone_offset_minutes": await db.get_timezone_offset(owner_id),
    }


class TimezoneUpdate(BaseModel):
    offset_minutes: int


@router.post("/account/timezone")
async def update_timezone(payload: TimezoneUpdate, user: dict = Depends(require_user)):
    if not -720 <= payload.offset_minutes <= 840:
        raise HTTPException(status_code=400, detail="Invalid timezone offset")
    await db.set_timezone_offset(user["id"], payload.offset_minutes)
    return {"offset_minutes": payload.offset_minutes}
