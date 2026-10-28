"""Настройки ИИ-ответов. Движок и модель безопасности — core/ai.py.

Важно для интерфейса: при включении владелец передаёт тексты переписки
стороннему провайдеру ИИ — это стоит показать явным предупреждением."""

import time
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import Owner, current_owner, require_user
from core import ai
from core import database as db

router = APIRouter()

TEST_LIMIT_PER_DAY = 20


async def _state(owner_id: int):
    stored = await db.get_ai_settings(owner_id) or {}
    now = int(time.time())
    return {
        "configured": ai.is_configured(),  # задан ли ключ провайдера на сервере
        "enabled": bool(stored.get("enabled", False)),
        "mode": stored.get("mode", "draft"),
        "instructions": stored.get("instructions"),
        "history_messages": stored.get("history_messages", 10),
        "daily_limit": stored.get("daily_limit", 30),
        "used_today": await ai.used_today(owner_id, "ai", now),
    }


@router.get("/ai")
async def get_ai(user: dict = Depends(require_user)):
    return await _state(user["id"])


class AiUpdate(BaseModel):
    enabled: bool | None = None
    mode: Literal["draft", "auto"] | None = None
    instructions: str | None = Field(
        default=None, max_length=ai.MAX_INSTRUCTIONS_LENGTH
    )
    history_messages: int | None = Field(default=None, ge=0, le=30)
    daily_limit: int | None = Field(default=None, ge=1, le=500)


@router.post("/ai")
async def update_ai(payload: AiUpdate, user: dict = Depends(require_user)):
    fields = {
        k: v for k, v in payload.model_dump().items() if k in payload.model_fields_set
    }
    for key in ("enabled", "mode", "history_messages", "daily_limit"):
        if key in fields and fields[key] is None:
            del fields[key]  # эти поля нельзя «обнулить»; instructions — можно

    if fields.get("enabled") and not ai.is_configured():
        raise HTTPException(
            status_code=409, detail="AI is not configured on the server"
        )

    await db.upsert_ai_settings(user["id"], **fields)
    return await _state(user["id"])


class AiTest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


@router.post("/ai/test")
async def test_ai(payload: AiTest, owner: Owner = Depends(current_owner)):
    """Пробный ответ по текущим инструкциям — без истории и без отправки."""
    user, connection = owner.user, owner.connection
    if not ai.is_configured():
        raise HTTPException(
            status_code=409, detail="AI is not configured on the server"
        )

    now = int(time.time())
    if await ai.used_today(user["id"], "ai_test", now) >= TEST_LIMIT_PER_DAY:
        raise HTTPException(status_code=429, detail="Daily test limit reached")

    stored = await db.get_ai_settings(user["id"]) or {}
    system = ai.build_system_prompt(
        stored.get("instructions"), connection.get("owner_name")
    )
    reply = await ai.complete(system, ai.build_messages([], payload.text))
    await db.log_autoreply(user["id"], 0, "ai_test", None, now)
    if reply is None:
        raise HTTPException(status_code=502, detail="AI provider request failed")
    return {"reply": reply}
