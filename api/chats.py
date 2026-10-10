"""Чаты, которые бот видел, и пометка прочитанными из мини-приложения.

Нужно, потому что команду .readall нельзя написать в «Избранном» или в личке
с ботом из бизнес-чата, а список чатов удобнее выбирать глазами."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_connection, require_user
from core import database as db
from core.readall import ReadFilter, find_chats, read_chats

router = APIRouter()


@router.get("/chats")
async def list_chats(user: dict = Depends(require_user)):
    connection = await require_connection(user["id"])
    chats = await db.list_recent_chats(connection["connection_id"], 200)
    incoming = {
        row["chat_id"]: row["last_at"]
        for row in await db.list_last_incoming_by_chat(connection["connection_id"])
    }
    favorites = await db.list_favorite_chat_ids(user["id"])
    return {
        "chats": [
            {
                "chat_id": chat["chat_id"],
                "last_at": chat["last_at"],
                "last_incoming_at": incoming.get(chat["chat_id"]),
                "favorite": chat["chat_id"] in favorites,
            }
            for chat in chats
        ]
    }


class ReadAllRequest(BaseModel):
    last_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    older_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    exclude_favorites: bool = False
    dry_run: bool = False  # только посчитать, сколько чатов подойдёт


@router.post("/readall")
async def read_all(payload: ReadAllRequest, user: dict = Depends(require_user)):
    connection = await require_connection(user["id"])
    flt = ReadFilter(
        last_seconds=payload.last_hours * 3600 if payload.last_hours else None,
        older_seconds=payload.older_hours * 3600 if payload.older_hours else None,
        exclude_fav=payload.exclude_favorites,
    )

    if payload.dry_run:
        return {"matched": len(await find_chats(connection, flt)), "done": 0, "failed": 0}

    from bot_instance import bot

    try:
        return await read_chats(bot, connection, flt)
    except Exception:
        raise HTTPException(status_code=502, detail="Telegram request failed")
