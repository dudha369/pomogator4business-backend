"""Расшифровка входящих голосовых в историю (настройка архива `voice_transcript`).

Middleware стоит сразу после записи истории: расшифровка идёт в фоне и дописывает
текст в уже сохранённую строку."""

import logging

from app.features.archive.prefs import load_prefs
from app.features.history.service import set_history_transcript
from app.platform.tasks import spawn
from app.platform.telegram.incoming import Incoming
from db.models.connection import get_connection
from db.models.user_locale import get_locale

logger = logging.getLogger("bot.archive.transcript")

VOICE_MAX_SECONDS = 120


async def transcribe_into_history(bot, connection_id, chat_id, message_id, voice):
    """Распознаёт голосовое и дописывает текст в историю."""
    try:
        from core.stt import transcribe_audio

        connection = await get_connection(connection_id)
        locale = await get_locale(connection["owner_id"]) if connection else "ru"
        file = await bot.get_file(voice.file_id)
        data = (await bot.download_file(file.file_path)).read()
        text = await transcribe_audio(data, locale)
    except Exception:
        logger.warning("Не удалось распознать голосовое %s", message_id, exc_info=True)
        return
    if text:
        await set_history_transcript(connection_id, chat_id, message_id, text)


async def voice_transcript(handler, message, data):
    inc: Incoming = data["inc"]
    voice = getattr(message, "voice", None)
    if (
        voice is not None
        and not inc.is_owner
        and inc.enabled("archive")
        and (getattr(voice, "duration", 0) or 0) <= VOICE_MAX_SECONDS
        and (await load_prefs(inc.connection_id)).voice_transcript
    ):
        spawn(
            transcribe_into_history(
                inc.bot, inc.connection_id, inc.chat_id, message.message_id, voice
            )
        )
    return await handler(message, data)
