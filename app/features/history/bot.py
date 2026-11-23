"""Запись истории и спасение исчезающего медиа: middleware бизнес-сообщений.

Порядок важен: `rescue_replied_media` идёт ДО `save_history` (как в прежнем конвейере).
"""

import logging
import time

from app.features.history.adapter import build_snapshot
from app.features.history.ingest import ingest
from app.features.history.service import get_history_entry, save_history
from app.platform.media import extract_history_media, extract_media_from_reply
from app.platform.telegram.incoming import Incoming
from config import settings

logger = logging.getLogger("bot.history")

# выключатель в настройках пользователя называется по-старому: «archive»
MEDIA_MODULE = "archive"


def media_fields(media):
    if media is None:
        return {}
    return {
        "media_type": media.kind,
        "media_data": media.data,
        "media_mime": media.mime,
        "media_name": media.name,
        "media_status": media.status,
    }


async def rescue_replied_media(handler, message, data):
    """Владелец ответил на сообщение, которого нет в истории (так выглядит исчезающее
    медиа: отдельным апдейтом оно не приходит). Достаём файл из reply_to_message сейчас,
    пока Telegram его туда вкладывает, и сохраняем БАЙТАМИ: file_id такого медиа может
    перестать работать, поэтому полагаться на него нельзя."""
    inc: Incoming = data["inc"]
    replied = message.reply_to_message
    if inc.enabled(MEDIA_MODULE) and inc.is_owner and replied is not None:
        await _rescue(inc, replied)
    return await handler(message, data)


async def _rescue(inc: Incoming, replied) -> None:
    existing = await get_history_entry(
        inc.connection_id, inc.chat_id, replied.message_id
    )
    if existing is not None:
        return

    try:
        rescued = await extract_media_from_reply(inc.bot, inc.message)
    except Exception:
        logger.warning(
            "Не удалось достать медиа из reply_to_message %s",
            replied.message_id,
            exc_info=True,
        )
        rescued = None

    logger.info(
        "rescue: reply_to=%s нет в истории; медиа=%s",
        replied.message_id,
        rescued.kind if rescued else None,
    )
    if rescued is not None:
        await save_history(
            inc.connection_id,
            inc.chat_id,
            replied.message_id,
            False,
            getattr(replied, "text", None) or getattr(replied, "caption", None),
            int(replied.date.timestamp()),
            snapshot=build_snapshot(replied, bot_id=getattr(inc.bot, "id", None)),
            **media_fields(rescued),
        )


async def record_history(handler, message, data):
    inc: Incoming = data["inc"]
    snapshot = build_snapshot(message, bot_id=getattr(inc.bot, "id", None))
    media = None

    if inc.enabled(MEDIA_MODULE) and settings.KEEP_MEDIA_BYTES:
        try:
            media = await extract_history_media(inc.bot, message)
        except Exception:
            logger.warning(
                "Ошибка извлечения медиа сообщения %s",
                message.message_id,
                exc_info=True,
            )

    if inc.text is not None or snapshot is not None:
        await ingest(
            source="bot",
            connection_id=inc.connection_id,
            chat_id=inc.chat_id,
            message_id=message.message_id,
            is_owner=inc.is_owner,
            text=inc.text,
            ts=int(message.date.timestamp()) if message.date else int(time.time()),
            snapshot=snapshot,
            media=media_fields(media),
        )
    return await handler(message, data)
