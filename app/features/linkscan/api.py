"""Настройки проверки ссылок в мини-приложении."""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.features.linkscan import queries
from app.features.linkscan.providers import PROVIDERS
from app.platform.api.deps import require_user

router = APIRouter()


class LinkscanOut(BaseModel):
    enabled: bool
    scope: Literal["all", "selected"]
    external: bool  # False — внешние сервисы не используются, наружу ничего не уходит
    chats: list[int]  # выбранные чаты (работают при scope = "selected")
    providers: dict[str, bool]  # какие сервисы настроены на сервере


class LinkscanUpdate(BaseModel):
    enabled: bool | None = None
    scope: Literal["all", "selected"] | None = None
    external: bool | None = None
    chats: list[int] | None = Field(default=None, max_length=1000)


async def _state(owner_id: int) -> dict:
    cfg = await queries.get_settings(owner_id)
    return {
        "enabled": cfg["enabled"],
        "scope": cfg["scope"],
        "external": cfg["external"],
        "chats": sorted(cfg["chats"]),
        "providers": {p.name: p.enabled() for p in PROVIDERS},
    }


@router.get("/linkscan", response_model=LinkscanOut)
async def get_linkscan(user: dict = Depends(require_user)):
    return await _state(user["id"])


@router.post("/linkscan", response_model=LinkscanOut)
async def update_linkscan(payload: LinkscanUpdate, user: dict = Depends(require_user)):
    fields = {
        k: v for k, v in payload.model_dump(exclude={"chats"}).items() if v is not None
    }
    await queries.update_settings(user["id"], chats=payload.chats, **fields)
    return await _state(user["id"])
