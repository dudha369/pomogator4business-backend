"""Счётчики для главной страницы мини-приложения."""

import time

from fastapi import APIRouter, Depends

from api.deps import require_connection, require_user
from core import database as db

router = APIRouter()


@router.get("/stats")
async def get_stats(user: dict = Depends(require_user)):
    """Сообщения за сегодня (по часовому поясу владельца) и за последние 7 суток.

    Считаются сообщения из истории: текст, подписи и сохранённое медиа
    (фото, видео, голосовые, кружки). Стикеры и файлы без подписи сюда не
    попадают — бот их не сохраняет."""
    connection = await require_connection(user["id"])
    offset_minutes = await db.get_timezone_offset(user["id"])

    now = int(time.time())
    local_now = now + offset_minutes * 60
    start_of_today = now - (local_now % 86400)
    week_ago = now - 7 * 86400

    today_total, today_incoming = await db.count_messages_since(
        connection["connection_id"], start_of_today
    )
    week_total, week_incoming = await db.count_messages_since(
        connection["connection_id"], week_ago
    )
    return {
        "today": {"total": today_total, "incoming": today_incoming},
        "week": {"total": week_total, "incoming": week_incoming},
    }
