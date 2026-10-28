"""Напоминания «собеседник написал, а вы не ответили».

Раз в 10 минут бот смотрит историю: если последнее сообщение в чате входящее
и ждёт ответа дольше N часов (настройка владельца), он присылает владельцу в
личку список таких чатов. Напоминание о каждой «серии» неотвеченных сообщений
приходит один раз; ответили — серия закрыта, написали снова — новая.

Не напоминаем: в «тихие часы», о чатах с флагом no_remind, при favorites_only —
о неизбранных, о сообщениях старше недели. Бот видит только текст и подписи
(см. step_history): стикеры и файлы без подписи в историю не попадают."""

import asyncio
import logging
import time

from core import database as db
from core.autoresponder import in_away_window
from core.i18n import t
from core.mentions import escape, mention

logger = logging.getLogger("bot.reminders")

LOOP_INTERVAL_SECONDS = 600
MAX_AGE_SECONDS = 7 * 86400
MAX_LINES = 10
PREVIEW_LENGTH = 80


# --------------------------- чистая логика ----------------------------------


def is_quiet(now: int, offset_minutes: int, start, end) -> bool:
    """Тихие часы владельца. Без расписания (None или start == end) — не тихо."""
    if start is None or end is None or start == end:
        return False
    return in_away_window(now, offset_minutes, start, end)


def compute_waiting(
    rows, now: int, min_seconds: int, max_seconds: int = MAX_AGE_SECONDS
):
    """Чаты, где последнее сообщение — входящее и ждёт ответа не меньше
    min_seconds (и не дольше max_seconds). Самые давние — первыми.
    rows — лёгкие строки истории {chat_id, message_id, is_owner, created_at}."""
    last = {}
    for row in rows:
        key = (row["created_at"], row["message_id"])
        current = last.get(row["chat_id"])
        if current is None or key > (current["created_at"], current["message_id"]):
            last[row["chat_id"]] = row
    waiting = []
    for chat_id, row in last.items():
        if row["is_owner"]:
            continue
        waited = now - row["created_at"]
        if min_seconds <= waited <= max_seconds:
            waiting.append(
                {
                    "chat_id": chat_id,
                    "message_id": row["message_id"],
                    "since": row["created_at"],
                    "waited_seconds": waited,
                }
            )
    return sorted(waiting, key=lambda w: (-w["waited_seconds"], w["chat_id"]))


def format_waited(seconds: int, locale: str) -> str:
    hours, rest = divmod(int(seconds), 3600)
    minutes = rest // 60
    if hours >= 24:
        return t("rem.unit_d", locale, n=hours // 24) + (
            " " + t("rem.unit_h", locale, n=hours % 24) if hours % 24 else ""
        )
    if hours:
        return t("rem.unit_h", locale, n=hours) + (
            " " + t("rem.unit_m", locale, n=minutes) if minutes else ""
        )
    return t("rem.unit_m", locale, n=max(minutes, 1))


# ------------------------------- сбор данных --------------------------------


async def find_waiting(
    connection, min_seconds, now, *, favorites_only=False, skip_reminded=True
):
    """Чаты, ждущие ответа, с учётом флагов, избранного и уже отправленных напоминаний."""
    owner_id = connection["owner_id"]
    rows = await db.list_history_rows_since(
        connection["connection_id"], now - MAX_AGE_SECONDS
    )
    candidates = compute_waiting(rows, now, min_seconds)
    if not candidates:
        return []

    flags = {f["chat_id"]: f for f in await db.list_chat_flags(owner_id)}
    favorites = await db.list_favorite_chat_ids(owner_id) if favorites_only else set()

    result = []
    for item in candidates:
        chat_id = item["chat_id"]
        if flags.get(chat_id, {}).get("no_remind"):
            continue
        if favorites_only and chat_id not in favorites:
            continue
        if skip_reminded:
            ref = await db.last_autoreply_ref(owner_id, chat_id, "reminder")
            if ref == str(item["message_id"]):
                continue  # об этой серии уже напоминали
        result.append(item)
    return result


async def render_list(bot, connection, items, locale: str) -> str:
    """HTML-текст со списком ждущих чатов (имена — упоминаниями, текст экранирован)."""
    lines = [t("rem.header", locale)]
    for item in items[:MAX_LINES]:
        entry = await db.get_history_entry(
            connection["connection_id"], item["chat_id"], item["message_id"]
        )
        preview = (entry["text"] or "") if entry else ""
        preview = escape(
            preview[:PREVIEW_LENGTH] + ("…" if len(preview) > PREVIEW_LENGTH else "")
        )
        who = await mention(bot, item["chat_id"], t("rem.someone", locale))
        lines.append(
            t(
                "rem.line",
                locale,
                who=who,
                ago=format_waited(item["waited_seconds"], locale),
                preview=preview,
            )
        )
    if len(items) > MAX_LINES:
        lines.append(t("rem.more", locale, count=len(items) - MAX_LINES))
    return "\n".join(lines)


# ------------------------------ оркестрация ---------------------------------


async def process_owner(bot, owner_id: int, now: int | None = None) -> int:
    """Одна проверка владельца. Возвращает число чатов в отправленном напоминании."""
    now = int(now if now is not None else time.time())
    cfg = await db.get_reminder_settings(owner_id)
    if not cfg or not cfg["enabled"]:
        return 0
    connection = await db.get_connection_by_owner(owner_id)
    if connection is None:
        return 0

    offset = await db.get_timezone_offset(owner_id)
    if is_quiet(now, offset, cfg["quiet_start_minutes"], cfg["quiet_end_minutes"]):
        return 0  # отправим на следующей проверке, когда тихие часы закончатся

    items = await find_waiting(
        connection, cfg["hours"] * 3600, now, favorites_only=cfg["favorites_only"]
    )
    if not items:
        return 0

    locale = await db.get_locale(owner_id)
    text = await render_list(bot, connection, items, locale)
    try:
        await bot.send_message(
            chat_id=connection["owner_chat_id"],
            text=text,
            parse_mode="html",
            disable_web_page_preview=True,
        )
    except Exception:
        logger.warning(
            "Не удалось отправить напоминание owner=%s", owner_id, exc_info=True
        )
        return 0

    for item in items:
        await db.log_autoreply(
            owner_id, item["chat_id"], "reminder", str(item["message_id"]), now
        )
    return len(items)


async def run_reminders_loop(bot):
    await asyncio.sleep(60)
    while True:
        try:
            for owner_id in await db.list_reminder_owner_ids():
                try:
                    await process_owner(bot, owner_id)
                except Exception:
                    logger.exception("Сбой напоминаний owner=%s", owner_id)
        except Exception:
            logger.exception("Сбой цикла напоминаний")
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)
