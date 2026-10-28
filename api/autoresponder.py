"""Настройки автоответчика: приветствие новому собеседнику, режим \"нет на
месте\" по расписанию, ответы по ключевым словам, авто-прочтение.

Сам движок — core/autoresponder.py. Подстановки в текстах: {name} и
{first_name} — имя собеседника, {full_name} — имя и фамилия."""

import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_user
from core import database as db
from core.autoresponder import in_away_window

router = APIRouter()

MAX_TEXT_LENGTH = 4096  # лимит Telegram на длину сообщения
MAX_KEYWORDS = 100


@router.get("/autoresponder")
async def get_settings(user: dict = Depends(require_user)):
    settings = await db.get_autoresponder_settings(user["id"])
    keywords = await db.list_keyword_replies(user["id"])
    away_start = settings["away_start_minutes"] if settings else None
    away_end = settings["away_end_minutes"] if settings else None
    offset = await db.get_timezone_offset(user["id"])
    return {
        "greeting_enabled": settings["greeting_enabled"] if settings else False,
        "greeting_text": settings["greeting_text"] if settings else None,
        "away_enabled": settings["away_enabled"] if settings else False,
        "away_text": settings["away_text"] if settings else None,
        "away_start_minutes": away_start,
        "away_end_minutes": away_end,
        # попадает ли сейчас «нет на месте» в расписание (по часовому поясу владельца)
        "away_active_now": in_away_window(
            int(time.time()), offset, away_start, away_end
        ),
        "auto_read_enabled": settings["auto_read_enabled"] if settings else False,
        "keywords": keywords,
    }


class AutoresponderUpdate(BaseModel):
    greeting_enabled: bool | None = None
    greeting_text: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    away_enabled: bool | None = None
    away_text: str | None = Field(default=None, max_length=MAX_TEXT_LENGTH)
    away_start_minutes: int | None = Field(default=None, ge=0, le=1439)
    away_end_minutes: int | None = Field(default=None, ge=0, le=1439)
    auto_read_enabled: bool | None = None


@router.post("/autoresponder")
async def update_settings(
    payload: AutoresponderUpdate, user: dict = Depends(require_user)
):
    # model_fields_set — чтобы можно было явно сбросить поле в null
    # (например, очистить расписание), а не только менять на непустое значение.
    fields = {
        k: v for k, v in payload.model_dump().items() if k in payload.model_fields_set
    }
    for key in ("greeting_enabled", "away_enabled", "auto_read_enabled"):
        if key in fields and fields[key] is None:
            del fields[key]

    # Нельзя включить режим, у которого нет текста: движок молча ничего бы не
    # отправлял, и владелец думал бы, что автоответчик работает.
    current = await db.get_autoresponder_settings(user["id"]) or {}
    merged = {**current, **fields}
    for flag, text_key in (
        ("greeting_enabled", "greeting_text"),
        ("away_enabled", "away_text"),
    ):
        if merged.get(flag) and not (merged.get(text_key) or "").strip():
            raise HTTPException(
                status_code=422, detail=f"{text_key} is required to enable this mode"
            )

    await db.upsert_autoresponder_settings(user["id"], **fields)
    return await get_settings(user=user)


class KeywordReplyCreate(BaseModel):
    keyword: str = Field(min_length=1, max_length=255)
    reply_text: str = Field(min_length=1, max_length=MAX_TEXT_LENGTH)


@router.post("/autoresponder/keywords")
async def create_keyword(
    payload: KeywordReplyCreate, user: dict = Depends(require_user)
):
    keyword = payload.keyword.strip().lower()
    if not keyword or not payload.reply_text.strip():
        raise HTTPException(
            status_code=422, detail="Keyword and reply must not be blank"
        )

    existing = {k["keyword"] for k in await db.list_keyword_replies(user["id"])}
    if keyword not in existing and len(existing) >= MAX_KEYWORDS:
        raise HTTPException(status_code=400, detail="Too many keywords")

    await db.add_keyword_reply(user["id"], keyword, payload.reply_text)
    return {"keyword": keyword, "reply_text": payload.reply_text}


@router.delete("/autoresponder/keywords/{keyword}")
async def remove_keyword(keyword: str, user: dict = Depends(require_user)):
    await db.delete_keyword_reply(user["id"], keyword.strip())
    return {"deleted": keyword.strip().lower()}
