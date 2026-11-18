"""«Не беспокоить» по чатам: отключение автоответов и/или ИИ для конкретного собеседника."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.features.chats.queries import list_chat_flags, set_chat_flags
from app.platform.api.deps import require_user
from app.platform.api.schemas import ChatFlags

router = APIRouter()


class ChatFlagsList(BaseModel):
    chats: list[ChatFlags]


@router.get("/chat-flags", response_model=ChatFlagsList)
async def list_flags(user: dict = Depends(require_user)):
    return {"chats": await list_chat_flags(user["id"])}


class ChatFlagsUpdate(BaseModel):
    chat_id: int
    no_autoreply: bool | None = None
    no_ai: bool | None = None
    no_remind: bool | None = None


@router.post("/chat-flags", response_model=ChatFlags)
async def update_flags(payload: ChatFlagsUpdate, user: dict = Depends(require_user)):
    changes = {
        key: value
        for key, value in payload.model_dump(exclude={"chat_id"}).items()
        if value is not None
    }
    flags = await set_chat_flags(user["id"], payload.chat_id, **changes)
    return {"chat_id": payload.chat_id, **flags}
