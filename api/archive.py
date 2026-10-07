from fastapi import APIRouter, Depends, Query

from api.deps import require_connection, require_user
from core import database as db

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
    )
    next_before_id = entries[-1]["log_id"] if entries and has_more else None
    return {"entries": entries, "has_more": has_more, "next_before_id": next_before_id}
