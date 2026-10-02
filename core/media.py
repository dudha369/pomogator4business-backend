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


async def rescue_via_reply(bot, connection_id, chat_id, message_id):
    """Техническая попытка 'спасти' self-destruct медиа: отвечаем на входящее
    сообщение от имени владельца сразу после получения — Telegram вкладывает
    полную копию оригинала (включая медиа) в reply_to_message нашего же
    технического ответа. Сам технический ответ тут же удаляем — собеседник
    не должен видеть лишнее сообщение."""
    try:
        probe = await bot.send_message(
            business_connection_id=connection_id,
            chat_id=chat_id,
            text="🔍",
            reply_parameters={"message_id": message_id},
        )
    except Exception:
        return None

    try:
        await bot.delete_business_messages(
            business_connection_id=connection_id, message_ids=[probe.message_id]
        )
    except Exception:
        pass

    original = probe.reply_to_message
    if original is None:
        return None
    return await extract_history_media(bot, original)
