"""Медиа записей архива: как оно описывается в API и откуда берутся байты.

Источники по порядку:
1. байты в самой записи архива (исчезающие медиа и записи до перехода на file_id);
2. байты в истории чата (старые записи);
3. Telegram по file_id из снимка — основной путь для новых записей: файл не
   лежит в нашей БД, мы скачиваем его по запросу (лимит Bot API — 20 МБ)."""

import logging

from core import database as db
from core.snapshot import FILE_KINDS, MAX_DOWNLOAD_BYTES, public_view

logger = logging.getLogger("bot.archive_media")

_DEFAULT_MIME = {
    "photo": "image/jpeg",
    "video": "video/mp4",
    "voice": "audio/ogg",
    "video_note": "video/mp4",
    "animation": "video/mp4",
    "audio": "audio/mpeg",
    "sticker": "image/webp",
    "document": "application/octet-stream",
}


def content_type(media_type, mime):
    return mime or _DEFAULT_MIME.get(media_type, "application/octet-stream")


def _snapshot_media(snap):
    """(kind, mime, name, status) файла из снимка или None."""
    if not snap or snap.get("kind") not in FILE_KINDS:
        return None
    if snap.get("file_size") and snap["file_size"] > MAX_DOWNLOAD_BYTES:
        status = "too_large"
    else:
        status = "remote" if snap.get("file_id") else "failed"
    return snap["kind"], snap.get("media_mime"), snap.get("media_name"), status


async def attach_media_info(connection_id, entries):
    """Дописывает в каждую запись поля old / new (описание содержимого для
    отрисовки) и media_type, media_mime, media_name, media_status,
    media_available (байты не загружаются)."""
    own_available = await db.list_log_media_availability(
        connection_id, [e["log_id"] for e in entries if e.get("media_type")]
    )
    # записи без снимков и без собственного медиа — смотрим в истории (старый формат)
    need_history = [
        e
        for e in entries
        if not e.get("media_type")
        and not e.get("old_snapshot")
        and not e.get("new_snapshot")
    ]
    from_history = await db.list_media_flags(
        connection_id, [(e["chat_id"], e["message_id"]) for e in need_history]
    )

    for entry in entries:
        old_snap = entry.pop("old_snapshot", None)
        new_snap = entry.pop("new_snapshot", None)
        entry["old"] = public_view(old_snap)
        entry["new"] = public_view(new_snap)

        # какое медиа показывать в списке: у правки — актуальное, у удаления — удалённое
        snap = (
            (new_snap or old_snap)
            if entry.get("event") == "edited"
            else (old_snap or new_snap)
        )
        described = _snapshot_media(snap)
        if entry.get("media_type"):
            entry["media_available"] = entry["log_id"] in own_available or (
                described is not None and described[3] == "remote"
            )
            continue
        if described:
            kind, mime, name, status = described
            entry.update(
                media_type=kind,
                media_mime=mime,
                media_name=name,
                media_status=status,
                media_available=status == "remote",
            )
            continue
        info = from_history.get((entry["chat_id"], entry["message_id"]))
        if info:
            entry["media_type"] = info["media_type"]
            entry["media_mime"] = info["media_mime"]
            entry["media_name"] = info["media_name"]
            entry["media_status"] = info["media_status"]
            entry["media_available"] = info["available"]
        else:
            entry.update(
                media_type=None,
                media_mime=None,
                media_name=None,
                media_status=None,
                media_available=False,
            )
    return entries


async def fetch_from_telegram(snap):
    """Скачивает файл снимка у Telegram по file_id; None, если нельзя."""
    if not snap or not snap.get("file_id"):
        return None
    size = snap.get("file_size")
    if size and size > MAX_DOWNLOAD_BYTES:
        return None
    import bot_instance

    bot = bot_instance.bot
    owner_bot = snap.get("bot_id")
    if owner_bot and getattr(bot, "id", owner_bot) != owner_bot:
        return None  # file_id выдан другим ботом (например, зеркальным)
    try:
        file = await bot.get_file(snap["file_id"])
        buffer = await bot.download_file(file.file_path)
        return buffer.read()
    except Exception:
        logger.warning("Не удалось скачать файл по file_id", exc_info=True)
        return None


async def load_media(connection_id, log_id, which="auto"):
    """(media_type, mime, name, bytes) для записи архива или None.

    which: old | new | auto (у правки — «новое», у удаления — «старое»)."""
    row = await db.get_log_media(connection_id, log_id)
    if row is None:
        return None
    if which == "auto":
        which = "new" if row.get("event") == "edited" else "old"

    if which == "old" and row["media_data"]:
        return (
            row["media_type"],
            row["media_mime"],
            row["media_name"],
            bytes(row["media_data"]),
        )

    snap = row.get(f"{which}_snapshot")
    if snap and snap.get("file_id"):
        data = await fetch_from_telegram(snap)
        if data is not None:
            kind = snap["kind"]
            return kind, snap.get("media_mime"), snap.get("media_name"), data

    if which == "old" or snap is None:
        history = await db.get_history_media(
            connection_id, row["chat_id"], row["message_id"]
        )
        if history and history["media_data"]:
            return (
                history["media_type"],
                history["media_mime"],
                history["media_name"],
                bytes(history["media_data"]),
            )
    return None
