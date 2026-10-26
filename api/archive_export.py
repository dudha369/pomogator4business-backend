"""Экспорт архива файлом.

Мини-приложение (WebView Telegram) плохо скачивает файлы, поэтому готовый
файл бот отправляет владельцу документом в личные сообщения — оттуда его
можно сохранить или переслать."""

import logging
import time
from typing import Literal

from aiogram.types import BufferedInputFile
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_connection, require_user
from core import archive_export as export
from core import database as db

logger = logging.getLogger("bot.archive_export")
router = APIRouter()

_MAX_FILE_BYTES = (
    45 * 1024 * 1024
)  # лимит Bot API на загрузку документа — 50 МБ, берём с запасом
_MAX_EMBEDDED_PHOTO_BYTES = 30 * 1024 * 1024
_MAX_CHAT_NAMES = 50
_PAGE = 1000

_running: set[int] = set()  # владельцы, у которых экспорт уже идёт


class ExportRequest(BaseModel):
    format: Literal["html", "csv", "json"] = "html"
    include_media: bool = False  # вшить фото в HTML (видео и голосовые не включаются)
    group_by_chat: bool = True
    # те же фильтры, что у вкладки «Архив»
    event: Literal["edited", "deleted"] | None = None
    search: str | None = None
    chat_id: int | None = None
    date_from: int | None = None
    date_to: int | None = None
    max_entries: int = Field(default=5000, ge=1, le=20000)


async def _collect_entries(connection_id, req: ExportRequest):
    entries, cursor = [], None
    while len(entries) < req.max_entries:
        page, has_more = await db.get_archive_page(
            connection_id,
            cursor,
            min(_PAGE, req.max_entries - len(entries)),
            event=req.event,
            search=req.search,
            chat_id=req.chat_id,
            date_from=req.date_from,
            date_to=req.date_to,
            ascending=True,
        )
        entries.extend(page)
        if not has_more or not page:
            break
        cursor = page[-1]["log_id"]
    truncated = len(entries) >= req.max_entries
    return entries, truncated


async def _chat_names(bot, chat_ids):
    names = {}
    for chat_id in list(dict.fromkeys(chat_ids))[:_MAX_CHAT_NAMES]:
        try:
            names[chat_id] = (await bot.get_chat(chat_id)).full_name
        except Exception:
            logger.debug("Не удалось получить имя чата %s", chat_id, exc_info=True)
    return names


async def _collect_photos(connection_id, entries):
    photos, total = {}, 0
    flags = await db.list_media_flags(
        connection_id, [(e["chat_id"], e["message_id"]) for e in entries]
    )
    for e in entries:
        if flags.get((e["chat_id"], e["message_id"])) != "photo":
            continue
        media = await db.get_history_media(connection_id, e["chat_id"], e["message_id"])
        if not media or not media["media_data"]:
            continue
        data = bytes(media["media_data"])
        if total + len(data) > _MAX_EMBEDDED_PHOTO_BYTES:
            break
        photos[e["log_id"]] = data
        total += len(data)
    return photos, flags


@router.post("/archive/export")
async def export_archive(req: ExportRequest, user: dict = Depends(require_user)):
    connection = await require_connection(user["id"])
    owner_id = user["id"]
    if owner_id in _running:
        raise HTTPException(status_code=429, detail="Export already running")

    _running.add(owner_id)
    try:
        entries, truncated = await _collect_entries(connection["connection_id"], req)
        if not entries:
            raise HTTPException(status_code=404, detail="Nothing to export")

        from bot_instance import bot

        # типы медиа нужны всем форматам (для подписи), байты фото — только HTML
        photos, flags = ({}, {})
        if req.format == "html" and req.include_media:
            photos, flags = await _collect_photos(connection["connection_id"], entries)
        else:
            flags = await db.list_media_flags(
                connection["connection_id"],
                [(e["chat_id"], e["message_id"]) for e in entries],
            )
        for e in entries:
            e["media_type"] = flags.get((e["chat_id"], e["message_id"]))

        names = await _chat_names(bot, [e["chat_id"] for e in entries])
        offset = await db.get_timezone_offset(owner_id)
        locale = await db.get_locale(owner_id)
        now = int(time.time())

        if req.format == "html":
            content = export.build_html(
                entries,
                names,
                offset,
                locale,
                now,
                photos=photos,
                group_by_chat=req.group_by_chat,
            )
        elif req.format == "csv":
            content = export.build_csv(
                entries, names, offset, locale, group_by_chat=req.group_by_chat
            )
        else:
            content = export.build_json(
                entries, names, offset, locale, now, group_by_chat=req.group_by_chat
            )

        if len(content) > _MAX_FILE_BYTES:
            raise HTTPException(
                status_code=413, detail="Export is too large; narrow the filters"
            )

        stamp = export.format_ts(now, offset)[:10]
        try:
            await bot.send_document(
                chat_id=connection["owner_chat_id"],
                document=BufferedInputFile(
                    content, filename=f"archive_{stamp}.{req.format}"
                ),
                caption=f"{export.labels(locale)['title']}: {len(entries)}",
            )
        except Exception:
            logger.exception("Не удалось отправить экспорт")
            raise HTTPException(status_code=502, detail="Telegram request failed")

        return {
            "sent": True,
            "entries": len(entries),
            "bytes": len(content),
            "truncated": truncated,
            "photos_embedded": len(photos),
        }
    finally:
        _running.discard(owner_id)
