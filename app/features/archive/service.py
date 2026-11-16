"""Логика архива без aiogram: что и когда записать, как связать версии и альбомы.

Принимает и возвращает словари/датаклассы. Отправка в Telegram — в `bot/`, текст
уведомлений — в `render/`, запросы к БД — в `queries.py` и `db.models.*`."""

import time
from collections.abc import Callable
from dataclasses import dataclass

from app.features.archive.prefs import ArchivePrefs, load_prefs
from app.features.archive.queries import get_edit_history, log_archive_event
from app.features.archive.snapshot import edit_kind
from app.features.history.snapshot import entry_snapshot, gift_sticker
from app.features.history.service import (
    delete_history,
    get_history_entry,
    list_album,
    save_history,
)
from db.models.module_settings import list_disabled_modules

TEXT_EDITS = ("text", "caption", "caption_removed", "media_caption")


async def is_enabled(connection_id) -> bool:
    return "archive" not in await list_disabled_modules(connection_id)


# --- мелкая логика ------------------------------------------------------------


def deleted_header_key(own: bool) -> str:
    """Telegram не говорит, кто удалил, поэтому заголовок называет только автора."""
    return "archive.deleted_header_own" if own else "archive.deleted_header"


def gift_sticker_id(snap):
    """file_id стикера подарка."""
    return snap.get("file_id") or (gift_sticker(snap.get("payload")) or {}).get(
        "file_id"
    )


def gift_summary(snap) -> str:
    """Коротко о подарке — для текста на кнопке."""
    payload = snap.get("payload") or {}
    gift = payload.get("gift") or {}
    if snap.get("kind") == "unique_gift":
        name = gift.get("base_name") or gift.get("name") or ""
        return f"{name} #{gift.get('number') or ''}".strip()
    parts = []
    if gift.get("star_count"):
        parts.append(f"⭐ {gift['star_count']}")
    if payload.get("text"):
        parts.append(payload["text"][:40])
    return " · ".join(parts)


def group_albums(items):
    """[(message_id, entry, snap)] -> группы: альбом (общий media_group_id) — одна группа."""
    units, by_group = [], {}
    for item in items:
        group_id = item[2].get("media_group_id")
        if not group_id:
            units.append([item])
        elif group_id in by_group:
            by_group[group_id].append(item)
        else:
            by_group[group_id] = [item]
            units.append(by_group[group_id])
    for unit in units:
        unit.sort(key=lambda item: item[0])
    return units


def edit_versions(previous, old, new, now, created_at=None):
    """Цепочка версий текста [первая … текущая] и время каждой.

    previous — прошлые правки этого сообщения из архива. Если цепочка не сходится
    (например, часть правок пропущена), начинаем с последней известной версии."""
    rows = [r for r in previous if r["edit_kind"] in TEXT_EDITS]
    versions = [rows[0]["old_text"] or ""] if rows else [old["text"] or ""]
    times = [created_at]
    for row in rows:
        versions.append(row["new_text"] or "")
        times.append(row["created_at"])
    if versions[-1] != (old["text"] or ""):
        versions, times = [old["text"] or ""], [None]
    versions.append(new["text"] or "")
    times.append(now)
    return versions, times


def last_notice_id(previous):
    """id уведомления, которое надо править при следующей правке текста."""
    return next(
        (
            r["notice_message_id"]
            for r in reversed(previous)
            if r["notice_message_id"] and r["edit_kind"] in TEXT_EDITS
        ),
        None,
    )


# --- удаления -----------------------------------------------------------------


async def collect_deleted(
    connection_id, chat_id, message_ids, is_self_delete: Callable[[int], bool]
):
    """Что показать об удалении: [(message_id, запись истории, снимок)].

    Удаления, которые сделал сам бот, в архив не идут — только чистим историю."""
    found = []
    for message_id in message_ids:
        if is_self_delete(message_id):
            await delete_history(connection_id, chat_id, message_id)
            continue
        entry = await get_history_entry(connection_id, chat_id, message_id)
        if entry is not None:
            found.append((message_id, entry, entry_snapshot(entry)))
    return found


async def record_deleted(connection_id, chat_id, unit, own: bool):
    """Журнал и очистка истории для группы (сообщение или альбом) одного автора."""
    for message_id, entry, snap in unit:
        await log_archive_event(
            connection_id,
            chat_id,
            message_id,
            "deleted",
            entry["text"],
            None,
            int(time.time()),
            kind=snap["kind"],
            old_snapshot=snap,
            is_owner=own,
            media_type=entry.get("media_type"),
            media_data=entry.get("media_data"),
            media_mime=entry.get("media_mime"),
            media_name=entry.get("media_name"),
            media_status=entry.get("media_status"),
        )
        await delete_history(connection_id, chat_id, message_id)


# --- правки -------------------------------------------------------------------


@dataclass
class EditPlan:
    is_owner: bool
    old: dict | None
    old_entry: dict | None
    change: str | None
    prefs: ArchivePrefs
    notify: bool


async def plan_edit(
    connection, chat_id, message_id, sender_id, snap, *, bot_edit: bool
) -> EditPlan:
    """Решает, уведомлять ли о правке. Правки самого бота (typewriter, ходы игр) в
    архив не попадают, как и правки владельца, пока он не включил `own_edits`."""
    connection_id = connection["connection_id"]
    is_owner = sender_id == connection["owner_id"]
    old_entry = await get_history_entry(connection_id, chat_id, message_id)
    old = entry_snapshot(old_entry)
    change = edit_kind(old, snap) if old is not None else None
    prefs = await load_prefs(connection_id)
    notify = bool(change) and not bot_edit and (not is_owner or prefs.own_edits)
    return EditPlan(is_owner, old, old_entry, change, prefs, notify)


async def previous_edits(connection_id, chat_id, message_id):
    return await get_edit_history(connection_id, chat_id, message_id)


async def album_entries(connection_id, chat_id, snap):
    if not snap.get("media_group_id"):
        return []
    return await list_album(connection_id, chat_id, snap["media_group_id"])


async def record_edit(
    connection_id, chat_id, message_id, plan: EditPlan, snap, notice_id
):
    """Журнал правки (если о ней уведомляли) и обновление истории до новой версии."""
    now = int(time.time())
    if plan.notify:
        await log_archive_event(
            connection_id,
            chat_id,
            message_id,
            "edited",
            plan.old["text"],
            snap["text"],
            now,
            kind=snap["kind"],
            edit_kind=plan.change,
            old_snapshot=plan.old,
            new_snapshot=snap,
            notice_message_id=notice_id,
            is_owner=plan.is_owner,
        )
    await save_history(
        connection_id,
        chat_id,
        message_id,
        plan.is_owner,
        snap["text"],
        now,
        snapshot=snap,
    )
