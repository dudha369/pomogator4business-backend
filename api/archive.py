"""GET /archive — постраничная лента архива (редактирования/удаления)
для вкладки «Архив» мини-приложения."""

from fastapi import APIRouter, Depends, Query

from api.deps import require_connection, require_user
from core import database as db

router = APIRouter()


@router.get("/archive")
async def get_archive(
    before_id: int | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=100),
    user: dict = Depends(require_user),
):
    connection = await require_connection(user["id"])
    entries, has_more = await db.get_archive_page(
        connection["connection_id"], before_id, limit
    )
    next_before_id = entries[-1]["log_id"] if entries and has_more else None
    return {
        "entries": entries,
        "has_more": has_more,
        "next_before_id": next_before_id,
    }
