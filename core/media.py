import logging

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


async def extract_history_media(bot, message):
    candidates = (
        ("photo", message.photo[-1] if message.photo else None),
        ("video", message.video),
        ("voice", message.voice),
        ("video_note", message.video_note),
    )
    for kind, obj in candidates:
        if obj is None:
            continue
        file_size = getattr(obj, "file_size", None)
        if file_size and file_size > _MAX_MEDIA_BYTES:
            return None, None
        file = await bot.get_file(obj.file_id)
        buffer = await bot.download_file(file.file_path)
        return kind, buffer.read()
    return None, None


async def extract_media_from_reply(bot, message):
    """Если владелец ответил на какое-то сообщение, а в нашей истории этого
    сообщения нет (характерно для self-destruct медиа, которое никогда не
    доходило до бота как отдельный апдейт) — пробуем достать медиа из
    reply_to_message прямо сейчас, пока Telegram ещё его туда вкладывает."""
    original = message.reply_to_message
    if original is None:
        return None, None
    return await extract_history_media(bot, original)
