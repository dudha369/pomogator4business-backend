"""Настройки напоминаний «вам не ответили». Логика — core/reminders.py."""

import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from api.deps import Owner, current_owner, require_user
from core import database as db
from core import reminders as reminders_core

router = APIRouter()


@router.get("/reminders")
async def get_reminders(user: dict = Depends(require_user)):
    cfg = await db.get_reminder_settings(user["id"]) or {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "hours": cfg.get("hours", 4),
        "quiet_start_minutes": cfg.get("quiet_start_minutes"),
        "quiet_end_minutes": cfg.get("quiet_end_minutes"),
        "favorites_only": bool(cfg.get("favorites_only", False)),
    }


class RemindersUpdate(BaseModel):
    enabled: bool | None = None
    hours: int | None = Field(default=None, ge=1, le=168)
    quiet_start_minutes: int | None = Field(default=None, ge=0, le=1439)
    quiet_end_minutes: int | None = Field(default=None, ge=0, le=1439)
    favorites_only: bool | None = None


@router.post("/reminders")
async def update_reminders(
    payload: RemindersUpdate, user: dict = Depends(require_user)
):
    # model_fields_set: тихие часы можно сбросить, передав null
    fields = {
        k: v for k, v in payload.model_dump().items() if k in payload.model_fields_set
    }
    for key in ("enabled", "hours", "favorites_only"):
        if key in fields and fields[key] is None:
            del fields[key]
    await db.upsert_reminder_settings(user["id"], **fields)
    return await get_reminders(user=user)


@router.get("/reminders/waiting")
async def waiting_now(owner: Owner = Depends(current_owner)):
    """Кто сейчас ждёт ответа (дольше настроенного порога) — для экрана настроек.
    Напоминания при этом не отправляются и не помечаются."""
    connection = owner.connection
    cfg = await db.get_reminder_settings(owner.id) or {}
    items = await reminders_core.find_waiting(
        connection,
        cfg.get("hours", 4) * 3600,
        int(time.time()),
        favorites_only=bool(cfg.get("favorites_only", False)),
        skip_reminded=False,
    )
    return {"chats": items}
