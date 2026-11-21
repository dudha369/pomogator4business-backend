"""Файлы кастомных (премиум) эмодзи для мини-приложения.

В сущностях сообщений хранится только `custom_emoji_id`; картинку отдаёт Telegram
через `getCustomEmojiStickers`. Файл эмодзи общий для всех (это стикер публичного
набора), поэтому проверка владельца не нужна — достаточно initData. Формат
(.tgs / .webm / .webp) фронтенд определяет по Content-Type."""

import time
from collections import OrderedDict

from fastapi import APIRouter, Depends, HTTPException, Path, Response

from app.platform.api.deps import require_user
from app.platform.media import download_custom_emoji

router = APIRouter()

# Эмодзи не меняется, «нет такого» может быть временным сбоем Telegram — кэш короче.
_TTL_FOUND = 24 * 3600
_TTL_MISSING = 600
_MAX_ENTRIES = 500  # ≤ ~100 КБ на запись в худшем случае
_cache: OrderedDict[str, tuple[float, tuple[bytes, str] | None]] = OrderedDict()


def _cached(emoji_id):
    hit = _cache.get(emoji_id)
    if hit and hit[0] > time.monotonic():
        _cache.move_to_end(emoji_id)
        return True, hit[1]
    return False, None


def _remember(emoji_id, value):
    _cache[emoji_id] = (
        time.monotonic() + (_TTL_FOUND if value else _TTL_MISSING),
        value,
    )
    _cache.move_to_end(emoji_id)
    while len(_cache) > _MAX_ENTRIES:
        _cache.popitem(last=False)  # вытесняем самое давнее, а не сбрасываем всё


@router.get(
    "/custom-emoji/{emoji_id}",
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
async def get_custom_emoji(
    emoji_id: str = Path(pattern=r"^\d{1,32}$"),
    _user: dict = Depends(require_user),
):
    from bot_instance import bot

    hit, value = _cached(emoji_id)
    if not hit:
        value = await download_custom_emoji(bot, emoji_id)
        _remember(emoji_id, value)
    if value is None:
        raise HTTPException(status_code=404, detail="Эмодзи не найдено")

    data, mime = value
    return Response(
        content=data,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )
