"""Стикеры интерфейса мини-приложения: `GET /api/ui-stickers/{name}`.

Имя берётся из реестра (`app.platform.ui_stickers`), файл отдаёт Telegram. Формат
(.tgs / .webm / .webp) фронтенд определяет по Content-Type, как у кастомных эмодзи.
Файл общий для всех, поэтому достаточно initData."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Response

from app.platform.api.deps import require_user
from app.platform.blob_cache import BlobCache
from app.platform.media import (
    StickerNotInSet,
    download_custom_emoji,
    download_set_sticker,
)
from app.platform.ui_stickers import REGISTRY, StickerName

logger = logging.getLogger("bot.ui_stickers")
router = APIRouter()
_cache = BlobCache(max_entries=100)


async def _fetch(name: str, bot):
    ref = REGISTRY[name]
    if ref.emoji_id:
        return await download_custom_emoji(bot, ref.emoji_id)
    try:
        return await download_set_sticker(bot, ref.set_name, ref.unique_id)
    except StickerNotInSet:
        # Ошибка реестра, а не сети: попадает в журнал ошибок и оповещает админов.
        logger.exception("Стикер интерфейса %s не найден в наборе", name)
        return None


@router.get(
    "/ui-stickers/{name}",
    response_class=Response,
    # байты файла (tgs/webm/webp), не JSON: response_model здесь не применим
    responses={
        200: {
            "content": {
                "application/x-tgsticker": {
                    "schema": {"type": "string", "format": "binary"}
                },
                "video/webm": {"schema": {"type": "string", "format": "binary"}},
                "image/webp": {"schema": {"type": "string", "format": "binary"}},
            }
        }
    },
)
async def get_ui_sticker(name: StickerName, _user: dict = Depends(require_user)):
    from bot_instance import bot

    key = str(name)
    hit, value = _cache.get(key)
    if not hit:
        value = await _fetch(key, bot)
        _cache.put(key, value)
    if value is None:
        raise HTTPException(status_code=404, detail="Стикер не найден")

    data, mime = value
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )
