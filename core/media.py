import logging
from dataclasses import dataclass

logger = logging.getLogger("bot.media_rescue")
_MAX_MEDIA_BYTES = 20 * 1024 * 1024


async def download_message_photo(bot, message):
    if not message or not message.photo:
        return None
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    buffer = await bot.download_file(file.file_path)
    return buffer.read()


async def download_user_avatar(bot, user_id):
    photos = await bot.get_user_profile_photos(user_id, limit=1)
    if not photos.photos:
        return None
    photo = photos.photos[0][-1]
    file = await bot.get_file(photo.file_id)
    buffer = await bot.download_file(file.file_path)
    return buffer.read()


@dataclass
class Media:
    """Медиа сообщения. data=None — файл не скачан (status говорит почему)."""

    kind: str  # photo | video | video_note | voice | animation | audio | sticker | document
    data: bytes | None
    mime: str | None = None
    name: str | None = None
    status: str = "saved"  # saved | too_large | failed


def _describe(message):
    """(kind, объект Telegram, mime, имя файла) первого найденного медиа или None.

    Порядок важен: у GIF-сообщения Telegram заполняет и animation, и document —
    animation проверяем раньше document."""
    if message.photo:
        return "photo", message.photo[-1], "image/jpeg", None
    if message.video:
        v = message.video
        return (
            "video",
            v,
            getattr(v, "mime_type", None) or "video/mp4",
            getattr(v, "file_name", None),
        )
    if message.video_note:
        return "video_note", message.video_note, "video/mp4", None
    if message.voice:
        v = message.voice
        return "voice", v, getattr(v, "mime_type", None) or "audio/ogg", None
    animation = getattr(message, "animation", None)
    if animation:
        return (
            "animation",
            animation,
            getattr(animation, "mime_type", None) or "video/mp4",
            getattr(animation, "file_name", None),
        )
    audio = getattr(message, "audio", None)
    if audio:
        name = getattr(audio, "file_name", None) or getattr(audio, "title", None)
        return "audio", audio, getattr(audio, "mime_type", None) or "audio/mpeg", name
    sticker = getattr(message, "sticker", None)
    if sticker:
        if getattr(sticker, "is_video", False):
            mime = "video/webm"
        elif getattr(sticker, "is_animated", False):
            mime = "application/x-tgsticker"
        else:
            mime = "image/webp"
        return "sticker", sticker, mime, None
    document = getattr(message, "document", None)
    if document:
        return (
            "document",
            document,
            getattr(document, "mime_type", None) or "application/octet-stream",
            getattr(document, "file_name", None),
        )
    return None


async def extract_history_media(bot, message):
    """Скачивает медиа сообщения. Возвращает Media или None, если медиа нет.

    Файл больше лимита Bot API (20 МБ) и сбой скачивания не теряются молча:
    возвращается Media с data=None и статусом — архив покажет причину."""
    described = _describe(message)
    if described is None:
        return None
    kind, obj, mime, name = described

    file_size = getattr(obj, "file_size", None)
    if file_size and file_size > _MAX_MEDIA_BYTES:
        return Media(kind, None, mime, name, "too_large")
    try:
        file = await bot.get_file(obj.file_id)
        buffer = await bot.download_file(file.file_path)
        return Media(kind, buffer.read(), mime, name, "saved")
    except Exception:
        logger.warning(
            "Не удалось скачать %s %s", kind, message.message_id, exc_info=True
        )
        return Media(kind, None, mime, name, "failed")


async def extract_media_from_reply(bot, message):
    """Если владелец ответил на какое-то сообщение, а в нашей истории этого
    сообщения нет (характерно для self-destruct медиа, которое никогда не
    доходило до бота как отдельный апдейт) — пробуем достать медиа из
    reply_to_message прямо сейчас, пока Telegram ещё его туда вкладывает."""
    original = message.reply_to_message
    if original is None:
        return None
    return await extract_history_media(bot, original)
