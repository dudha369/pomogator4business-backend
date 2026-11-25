"""Юзербот в мини-приложении: статус, вход по QR (с паролем 2FA), отключение."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.features.userbot import login, qr, service
from app.features.userbot.manager import manager
from app.platform.api.deps import require_user
from db.models.connection import get_connection_by_owner

router = APIRouter()

Reason = Literal["not_configured", "no_encryption"]
Status = Literal["none", "login", "connecting", "connected", "revoked", "removing"]


class LoginOut(BaseModel):
    state: Literal["starting", "qr", "password", "done", "error"]
    qr: str | None  # data-URI PNG; только в состоянии qr
    error: str | None


class UserbotOut(BaseModel):
    reason: Reason | None  # почему вход невозможен
    status: Status
    username: str | None
    login: LoginOut | None


class LoginIn(BaseModel):
    consent: bool


class PasswordIn(BaseModel):
    password: str = Field(min_length=1, max_length=256)


async def _state(owner_id: int) -> dict:
    state = await service.get_status(owner_id)
    flow = state.pop("login")
    state["login"] = None
    if flow:
        url = flow.pop("qr_url")
        flow["qr"] = await asyncio.to_thread(qr.render_data_uri, url) if url else None
        state["login"] = flow
    return state


@router.get("/userbot", response_model=UserbotOut)
async def get_userbot(user: dict = Depends(require_user)):
    return await _state(user["id"])


@router.post("/userbot/login", response_model=UserbotOut)
async def start_login(payload: LoginIn, user: dict = Depends(require_user)):
    if not payload.consent:
        raise HTTPException(status_code=400, detail={"reason": "consent_required"})
    if reason := await service.start_login(user["id"]):
        raise HTTPException(status_code=409, detail={"reason": reason})
    return await _state(user["id"])


@router.post("/userbot/login/password", response_model=UserbotOut)
async def submit_password(payload: PasswordIn, user: dict = Depends(require_user)):
    if not await login.submit_password(user["id"], payload.password):
        raise HTTPException(status_code=409, detail={"reason": "not_waiting_password"})
    return await _state(user["id"])


@router.delete("/userbot", response_model=UserbotOut)
async def disconnect(user: dict = Depends(require_user)):
    await service.disconnect(user["id"])
    return await _state(user["id"])


class DialogOut(BaseModel):
    id: int  # chat_id в формате Bot API
    kind: Literal["private", "group", "supergroup", "channel"]
    title: str
    username: str | None
    members: int | None
    archived: bool


class DialogsOut(BaseModel):
    dialogs: list[DialogOut]
    has_more: bool


@router.get("/userbot/dialogs", response_model=DialogsOut)
async def get_dialogs(
    q: str | None = Query(default=None, max_length=100),
    kind: str | None = Query(
        default=None, pattern="^(private|group|supergroup|channel)$"
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(require_user),
):
    """Диалоги аккаунта для экрана выбора чатов. Живой запрос к Telegram (кэш пару
    минут): список нигде не хранится. Клиент работает в процессе с блокировкой, и в окне
    деплоя этот процесс может быть другим — тогда 503, повторить через несколько секунд."""
    try:
        items = await manager.dialogs(user["id"])
    except Exception:
        items = None
    if items is None:
        raise HTTPException(status_code=503, detail={"reason": "userbot_unavailable"})
    business = await get_connection_by_owner(user["id"])
    needle = (q or "").casefold()
    shown = [
        d
        for d in items
        # личные чаты ведёт бизнес-бот, пока он подключён; боты в архив не нужны
        if not d.is_bot
        and not (d.kind == "private" and business and business["is_enabled"])
        and (kind is None or d.kind == kind)
        and (not needle or needle in f"{d.title} {d.username or ''}".casefold())
    ]
    page = shown[offset : offset + limit]
    return {"dialogs": page, "has_more": offset + limit < len(shown)}
