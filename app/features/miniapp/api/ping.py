"""Проверка связи с сервером для мини-приложения.

GET /api/ping       — без авторизации и без обращений к БД/Telegram: фронтенд
                      сам замеряет круговое время запроса (это и есть «пинг»).
GET /api/ping/deep  — с авторизацией: задержки БД и Telegram API и аптайм."""

import time

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel

from app.platform.api.deps import require_user
from app.platform.health import measure_health

router = APIRouter()


class PingOut(BaseModel):
    ok: bool
    server_time_ms: int


class HealthOut(BaseModel):
    telegram_ms: int | None  # None — Telegram не ответил за таймаут
    db_ms: int | None
    uptime_seconds: int


@router.get("/ping", response_model=PingOut)
async def ping(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "server_time_ms": int(time.time() * 1000)}


@router.get("/ping/deep", response_model=HealthOut)
async def ping_deep(response: Response, user: dict = Depends(require_user)):
    from bot_instance import bot

    response.headers["Cache-Control"] = "no-store"
    return await measure_health(bot)
