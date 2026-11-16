"""Язык интерфейса владельца."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from db.models import user_locale as locale_db
from app.platform.i18n import LANGUAGE_NAMES

router = APIRouter()


class LocaleOut(BaseModel):
    locale: str


@router.get("/locale", response_model=LocaleOut)
async def get_locale(user: dict = Depends(require_user)):
    return {"locale": await locale_db.get_locale(user["id"])}


class LocaleUpdate(BaseModel):
    locale: str


@router.post("/locale", response_model=LocaleOut)
async def update_locale(payload: LocaleUpdate, user: dict = Depends(require_user)):
    if payload.locale not in LANGUAGE_NAMES:
        raise HTTPException(status_code=400, detail="Unsupported locale")

    await locale_db.set_locale(user["id"], payload.locale)
    return {"locale": payload.locale}
