"""Настройки автоответчика: приветствие новому собеседнику, режим "нет на
месте" по расписанию, ответы по ключевым словам, авто-прочтение."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import require_user
from core import database as db

router = APIRouter()


@router.get("/autoresponder")
async def get_settings(user: dict = Depends(require_user)):
    settings = await db.get_autoresponder_settings(user["id"])
    keywords = await db.list_keyword_replies(user["id"])
    return {
        "greeting_enabled": settings["greeting_enabled"] if settings else False,
        "greeting_text": settings["greeting_text"] if settings else None,
        "away_enabled": settings["away_enabled"] if settings else False,
        "away_text": settings["away_text"] if settings else None,
        "away_start_minutes": settings["away_start_minutes"] if settings else None,
        "away_end_minutes": settings["away_end_minutes"] if settings else None,
        "auto_read_enabled": settings["auto_read_enabled"] if settings else False,
        "keywords": keywords,
    }


class AutoresponderUpdate(BaseModel):
    greeting_enabled: bool | None = None
    greeting_text: str | None = None
    away_enabled: bool | None = None
    away_text: str | None = None
    away_start_minutes: int | None = None
    away_end_minutes: int | None = None
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
    await db.upsert_autoresponder_settings(user["id"], **fields)
    return await get_settings(user=user)


class KeywordReplyCreate(BaseModel):
    keyword: str
    reply_text: str


@router.post("/autoresponder/keywords")
async def create_keyword(
    payload: KeywordReplyCreate, user: dict = Depends(require_user)
):
    await db.add_keyword_reply(user["id"], payload.keyword, payload.reply_text)
    return {"keyword": payload.keyword.lower(), "reply_text": payload.reply_text}


@router.delete("/autoresponder/keywords/{keyword}")
async def remove_keyword(keyword: str, user: dict = Depends(require_user)):
    await db.delete_keyword_reply(user["id"], keyword)
    return {"deleted": keyword.lower()}
