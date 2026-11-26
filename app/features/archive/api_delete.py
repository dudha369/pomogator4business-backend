"""Удаление записей архива владельцем: выбранные записи или только их файлы."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.features.archive.queries import delete_entries
from app.features.archive.scope import ArchiveScope, archive_scope

router = APIRouter()

MAX_IDS = 500  # за один запрос; больше — несколькими


class DeleteIn(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=MAX_IDS)
    media_only: bool = False  # True — убрать только файлы, записи остаются


class DeleteOut(BaseModel):
    count: int  # затронуто записей (чужие id не считаются)
    freed_bytes: int


@router.delete("/archive", response_model=DeleteOut)
async def delete_archive(body: DeleteIn, scope: ArchiveScope = Depends(archive_scope)):
    count, freed = await delete_entries(
        scope.connection_ids, ids=body.ids, media_only=body.media_only
    )
    return {"count": count, "freed_bytes": freed}
