import urllib.parse

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from api.deps import Owner, current_owner
from core import database as db
from core.archive_media import attach_media_info, content_type, load_media
from core.archive_prefs import ALBUM_STYLES, RICH_KINDS, load_prefs, update_prefs

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
async def get_archive_media(
    log_id: int,
    which: str = Query(default="auto", pattern="^(auto|old|new)$"),
    owner: Owner = Depends(current_owner),
):
    connection = owner.connection
    media = await load_media(connection["connection_id"], log_id, which)
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


class ArchivePrefsPatch(BaseModel):
    """Частичное обновление: присылайте только то, что изменилось."""

    rich: bool | None = None
    rich_kinds: list[str] | None = None
    album_style: str | None = None
    collapse_media: bool | None = None
    edit_history: bool | None = None
    caption_edit_media: bool | None = None
    location_map: bool | None = None
    voice_transcript: bool | None = None


def _prefs_response(prefs):
    return {
        "prefs": prefs.as_dict(),
        # допустимые значения — чтобы интерфейс не хранил их у себя копией
        "options": {"album_style": list(ALBUM_STYLES), "rich_kinds": list(RICH_KINDS)},
    }


@router.get("/archive/settings")
async def get_archive_settings(owner: Owner = Depends(current_owner)):
    return _prefs_response(await load_prefs(owner.connection["connection_id"]))


@router.post("/archive/settings")
async def update_archive_settings(
    patch: ArchivePrefsPatch, owner: Owner = Depends(current_owner)
):
    changes = patch.model_dump(exclude_none=True)
    try:
        prefs = await update_prefs(owner.connection["connection_id"], changes)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _prefs_response(prefs)
