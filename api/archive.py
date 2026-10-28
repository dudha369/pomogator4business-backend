import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api.deps import Owner, current_owner
from core import database as db
from core.archive_media import attach_media_info, content_type, load_media

router = APIRouter()


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
    owner: Owner = Depends(current_owner),
):
    connection = owner.connection
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

    await attach_media_info(connection["connection_id"], entries)

    next_cursor = entries[-1]["log_id"] if entries and has_more else None
    return {
        "entries": entries,
        "has_more": has_more,
        "next_before_id": next_cursor,
    }


@router.get("/archive/{log_id}/media")
async def get_archive_media(log_id: int, owner: Owner = Depends(current_owner)):
    connection = owner.connection
    media = await load_media(connection["connection_id"], log_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Медиа не сохранено")

    media_type, mime, name, data = media
    headers = {"Cache-Control": "private, max-age=3600"}
    if name:
        headers["Content-Disposition"] = (
            f"inline; filename*=UTF-8''{urllib.parse.quote(name)}"
        )
    return Response(
        content=data, media_type=content_type(media_type, mime), headers=headers
    )
