from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.features.chats.queries import is_known_chat
from app.platform.api.deps import require_user

router = APIRouter()


class ChatInfoOut(BaseModel):
    full_name: str
    username: str | None


@router.get("/chat-info/{target_user_id}", response_model=ChatInfoOut)
async def get_chat_info(target_user_id: int, user: dict = Depends(require_user)):
    is_known = await is_known_chat(user["id"], target_user_id)
    if not is_known:
        raise HTTPException(status_code=404, detail="Unknown chat")

    from bot_instance import bot

    try:
        chat = await bot.get_chat(target_user_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {"full_name": chat.full_name, "username": chat.username}
