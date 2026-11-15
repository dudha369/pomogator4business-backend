"""Счётчики для главной страницы мини-приложения."""

import time

from fastapi import APIRouter, Depends, Query

from api.deps import Owner, current_owner
from db.models.archive_log import count_archive_events_since
from db.models.message_history import (
    count_by_chat,
    count_by_day,
    count_messages_since,
    list_history_rows_since,
)
from db.models.user_locale import get_timezone_offset
from core import stats as stats_calc

router = APIRouter()


@router.get("/stats")
async def get_stats(owner: Owner = Depends(current_owner)):
    """Сообщения за сегодня (по часовому поясу владельца) и за последние 7 суток.

    Считаются сообщения из истории: текст, подписи и сохранённое медиа
    (фото, видео, голосовые, кружки). Стикеры и файлы без подписи сюда не
    попадают — бот их не сохраняет."""
    user, connection = owner.user, owner.connection
    offset_minutes = await get_timezone_offset(user["id"])

    now = int(time.time())
    local_now = now + offset_minutes * 60
    start_of_today = now - (local_now % 86400)
    week_ago = now - 7 * 86400

    today_total, today_incoming = await count_messages_since(
        connection["connection_id"], start_of_today
    )
    week_total, week_incoming = await count_messages_since(
        connection["connection_id"], week_ago
    )
    return {
        "today": {"total": today_total, "incoming": today_incoming},
        "week": {"total": week_total, "incoming": week_incoming},
    }


@router.get("/stats/overview")
async def get_overview(
    days: int = Query(default=30, ge=1, le=90),
    owner: Owner = Depends(current_owner),
):
    """Динамика по дням, топ собеседников, удалённые/изменённые и скорость
    ответа за последние `days` суток (по сохранённой истории)."""
    user, connection = owner.user, owner.connection
    offset = await get_timezone_offset(user["id"])
    now = int(time.time())
    since = now - days * 86400

    connection_id = connection["connection_id"]
    # счёт и топ — SQL-агрегатами; в память грузим только лёгкие строки для скорости ответа
    rows = await list_history_rows_since(connection_id, since)
    return {
        "days": stats_calc.daily_from_counts(
            await count_by_day(connection_id, since, offset), now, offset, days
        ),
        "top_chats": stats_calc.top_from_counts(
            await count_by_chat(connection_id, since)
        ),
        "archive": await count_archive_events_since(
            connection["connection_id"], since
        ),
        "reply_time": stats_calc.reply_summary(stats_calc.reply_times(rows)),
    }
