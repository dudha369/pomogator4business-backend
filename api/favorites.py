"""Избранные чаты — пометка из команды .fav, используется фильтром nofav в .readall."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import Owner, current_owner
from core import database as db

router = APIRouter()


@router.get("/favorites")
async def list_favorites(owner: Owner = Depends(current_owner)):
    user = owner.user
    return {"chat_ids": sorted(await db.list_favorite_chat_ids(user["id"]))}


class FavoriteUpdate(BaseModel):
    chat_id: int
    favorite: bool


@router.post("/favorites")
async def set_favorite(payload: FavoriteUpdate, owner: Owner = Depends(current_owner)):
    user = owner.user
    await db.set_favorite_chat(user["id"], payload.chat_id, payload.favorite)
    return {"chat_id": payload.chat_id, "favorite": payload.favorite}
