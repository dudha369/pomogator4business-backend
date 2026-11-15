"""Язык интерфейса владельца."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from core import database as db
from core.i18n import LANGUAGE_NAMES

router = APIRouter()


@router.get("/locale")
async def get_locale(user: dict = Depends(require_user)):
    return {"locale": await db.get_locale(user["id"])}


class LocaleUpdate(BaseModel):
    locale: str


@router.post("/locale")
async def update_locale(payload: LocaleUpdate, user: dict = Depends(require_user)):
    if payload.locale not in LANGUAGE_NAMES:
        raise HTTPException(status_code=400, detail="Unsupported locale")

    await db.set_locale(user["id"], payload.locale)
    return {"locale": payload.locale}
