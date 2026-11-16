"""Избранные чаты — пометка из команды .fav, используется фильтром nofav в .readall."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from api.deps import Owner, current_owner
from db.models.favorite_chat import list_favorite_chat_ids, set_favorite_chat

router = APIRouter()


class FavoritesOut(BaseModel):
    chat_ids: list[int]


class FavoriteOut(BaseModel):
    chat_id: int
    favorite: bool


@router.get("/favorites", response_model=FavoritesOut)
async def list_favorites(owner: Owner = Depends(current_owner)):
    user = owner.user
    return {"chat_ids": sorted(await list_favorite_chat_ids(user["id"]))}


class FavoriteUpdate(BaseModel):
    chat_id: int
    favorite: bool


@router.post("/favorites", response_model=FavoriteOut)
async def set_favorite(payload: FavoriteUpdate, owner: Owner = Depends(current_owner)):
    user = owner.user
    await set_favorite_chat(user["id"], payload.chat_id, payload.favorite)
    return {"chat_id": payload.chat_id, "favorite": payload.favorite}
