"""«Не беспокоить» по чатам: отключение автоответов и/или ИИ для конкретного собеседника."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import require_user
from core import database as db

router = APIRouter()


@router.get("/chat-flags")
async def list_flags(user: dict = Depends(require_user)):
    return {"chats": await db.list_chat_flags(user["id"])}


class ChatFlagsUpdate(BaseModel):
    chat_id: int
    no_autoreply: bool | None = None
    no_ai: bool | None = None
    no_remind: bool | None = None


@router.post("/chat-flags")
async def update_flags(payload: ChatFlagsUpdate, user: dict = Depends(require_user)):
    changes = {
        key: value
        for key, value in payload.model_dump(exclude={"chat_id"}).items()
        if value is not None
    }
    flags = await db.set_chat_flags(user["id"], payload.chat_id, **changes)
    return {"chat_id": payload.chat_id, **flags}
