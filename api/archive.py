from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.deps import require_connection, require_user
from core import database as db
from db.models.archive_log import ArchiveLog

router = APIRouter()

_MEDIA_CONTENT_TYPES = {
    "photo": "image/jpeg",
    "video": "video/mp4",
    "voice": "audio/ogg",
    "video_note": "video/mp4",
}


@router.get("/archive")
async def get_archive(
    before_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    event: str | None = Query(default=None, pattern="^(edited|deleted)$"),
    search: str | None = Query(default=None),
    chat_id: int | None = Query(default=None),
    date_from: int | None = Query(default=None),
    date_to: int | None = Query(default=None),
    sort: str = Query(default="desc", pattern="^(asc|desc)$"),
    user: dict = Depends(require_user),
):
    connection = await require_connection(user["id"])
    entries, has_more = await db.get_archive_page(
        connection["connection_id"],
        before_id,
        limit,
        event=event,
        search=search,
        chat_id=chat_id,
        date_from=date_from,
        date_to=date_to,
        ascending=(sort == "asc"),
    )

    # media_type отдаём только если байты реально сохранены (иначе кнопка
    # «показать медиа» вела бы в 404 — например, после очистки по сроку)
    flags = await db.list_media_flags(
        connection["connection_id"],
        [(e["chat_id"], e["message_id"]) for e in entries],
    )
    for entry in entries:
        entry["media_type"] = flags.get((entry["chat_id"], entry["message_id"]))

    next_cursor = entries[-1]["log_id"] if entries and has_more else None
    return {
        "entries": entries,
        "has_more": has_more,
        "next_before_id": next_cursor,
    }


@router.get("/archive/{log_id}/media")
async def get_archive_media(log_id: int, user: dict = Depends(require_user)):
    connection = await require_connection(user["id"])
    rows = await ArchiveLog.filter(
        log_id=log_id, connection_id=connection["connection_id"]
    ).values("chat_id", "message_id")
    if not rows:
        raise HTTPException(status_code=404, detail="Запись архива не найдена")

    media = await db.get_history_media(
        connection["connection_id"], rows[0]["chat_id"], rows[0]["message_id"]
    )
    if not media or not media["media_data"]:
        raise HTTPException(status_code=404, detail="Медиа не сохранено")

    return Response(
        content=bytes(media["media_data"]),
        media_type=_MEDIA_CONTENT_TYPES.get(media["media_type"], "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=3600"},
    )
