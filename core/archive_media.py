"""Медиа записей архива: как оно описывается в API и откуда берутся байты.

Источник — сама запись архива (для удалённых сообщений: фото, видео, кружок,
голосовое, GIF, аудио, стикер, документ сохраняются вместе с ней). Для старых
записей и для «изменённых» сообщений медиа подтягивается из истории чата."""

from core import database as db

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


async def attach_media_info(connection_id, entries):
    """Дописывает в каждую запись поля media_type, media_mime, media_name,
    media_status, media_available (байты не загружаются)."""
    own_available = await db.list_log_media_availability(
        connection_id, [e["log_id"] for e in entries if e.get("media_type")]
    )
    # записи без собственного медиа (например «изменено») — смотрим в истории
    need_history = [e for e in entries if not e.get("media_type")]
    from_history = await db.list_media_flags(
        connection_id, [(e["chat_id"], e["message_id"]) for e in need_history]
    )

    for entry in entries:
        if entry.get("media_type"):
            entry["media_available"] = entry["log_id"] in own_available
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


async def load_media(connection_id, log_id):
    """(media_type, mime, name, bytes) для записи архива или None."""
    row = await db.get_log_media(connection_id, log_id)
    if row is None:
        return None
    if row["media_data"]:
        return (
            row["media_type"],
            row["media_mime"],
            row["media_name"],
            bytes(row["media_data"]),
        )

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
