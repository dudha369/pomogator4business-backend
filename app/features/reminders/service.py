"""Напоминания «собеседник написал, а вы не ответили».

Раз в 10 минут бот смотрит историю: если последнее сообщение в чате входящее
и ждёт ответа дольше N часов (настройка владельца), он присылает владельцу в
личку список таких чатов. Напоминание о каждой «серии» неотвеченных сообщений
приходит один раз; ответили — серия закрыта, написали снова — новая.

Не напоминаем: в «тихие часы», о чатах с флагом no_remind, при favorites_only —
о неизбранных, о сообщениях старше недели. Бот видит только текст и подписи
(см. app.features.history.bot.record_history): стикеры и файлы без подписи в историю не попадают.
"""

from app.features.autoresponder.queries import last_autoreply_ref
from app.features.autoresponder.service import in_away_window
from app.features.chats.queries import list_chat_flags, list_favorite_chat_ids
from app.features.history.service import last_rows_by_chat
from app.features.reminders.models import ReminderSettings
from app.platform.i18n import t

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


async def find_waiting(
    connection, min_seconds, now, *, favorites_only=False, skip_reminded=True
):
    """Чаты, ждущие ответа, с учётом флагов, избранного и уже отправленных напоминаний."""
    owner_id = connection["owner_id"]
    rows = await last_rows_by_chat(connection["connection_id"], now - MAX_AGE_SECONDS)
    candidates = compute_waiting(rows, now, min_seconds)
    if not candidates:
        return []

    flags = {f["chat_id"]: f for f in await list_chat_flags(owner_id)}
    favorites = await list_favorite_chat_ids(owner_id) if favorites_only else set()

    result = []
    for item in candidates:
        chat_id = item["chat_id"]
        if flags.get(chat_id, {}).get("no_remind"):
            continue
        if favorites_only and chat_id not in favorites:
            continue
        if skip_reminded:
            ref = await last_autoreply_ref(owner_id, chat_id, "reminder")
            if ref == str(item["message_id"]):
                continue  # об этой серии уже напоминали
        result.append(item)
    return result


async def get_reminder_settings(owner_id):
    rows = await ReminderSettings.filter(owner_id=owner_id).values()
    return rows[0] if rows else None


async def upsert_reminder_settings(owner_id, **fields_):
    await ReminderSettings.update_or_create(owner_id=owner_id, defaults=fields_)


async def list_reminder_owner_ids():
    return await ReminderSettings.filter(enabled=True).values_list(
        "owner_id", flat=True
    )
