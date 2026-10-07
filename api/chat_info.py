"""Отдаёт актуальные имя/username собеседника по его user_id (он же chat_id
в бизнес-чате) напрямую через Bot API — без хранения в БД, потому что эти
данные могут меняться, а Telegram и так отдаёт их по запросу для любого,
кто хоть раз писал этому владельцу (то же условие доступа, что и для
аватарки в api/avatar.py)."""

from fastapi import APIRouter, Depends, HTTPException

from api.deps import require_user
from core import database as db

router = APIRouter()


@router.get("/chat-info/{target_user_id}")
async def get_chat_info(target_user_id: int, user: dict = Depends(require_user)):
    is_known = await db.is_known_chat(user["id"], target_user_id)
    if not is_known:
        raise HTTPException(status_code=404, detail="Unknown chat")

    from bot_instance import bot

    try:
        chat = await bot.get_chat(target_user_id)
    except Exception:
        raise HTTPException(status_code=404, detail="Chat not found")

    return {"full_name": chat.full_name, "username": chat.username}
