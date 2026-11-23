"""Юзербот в мини-приложении: статус, вход по QR (с паролем 2FA), отключение."""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.features.userbot import login, qr, service
from app.platform.api.deps import require_user

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
