"""Проверка связи с сервером для мини-приложения.

GET /api/ping       — без авторизации и без обращений к БД/Telegram: фронтенд
                      сам замеряет круговое время запроса (это и есть «пинг»).
GET /api/ping/deep  — с авторизацией: задержки БД и Telegram API и аптайм."""

import time

from fastapi import APIRouter, Depends, Response

from api.deps import require_user
from core.health import measure_health

router = APIRouter()


@router.get("/ping")
async def ping(response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"ok": True, "server_time_ms": int(time.time() * 1000)}


@router.get("/ping/deep")
async def ping_deep(response: Response, user: dict = Depends(require_user)):
    from bot_instance import bot

    response.headers["Cache-Control"] = "no-store"
    return await measure_health(bot)