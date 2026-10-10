import logging
import time

from aiogram import Bot, Router
from aiogram.types import Message

from core import database as db
from core.context import CommandContext
from core.media import extract_history_media, extract_media_from_reply
from core.registry import registry
from modules.mute import handle_incoming as handle_mute_incoming
from modules.scam import handle_new_contact
from modules.type_ import TYPE_TRIGGERS, handle_type_trigger
from modules.voice_effects import handle_voice_message
from modules.wordle import handle_wordle_guess

logger = logging.getLogger("bot.business_messages")
router = Router(name="business_messages")


@router.business_message()
async def on_business_message(message: Message, bot: Bot):
    connection = await db.get_connection(message.business_connection_id)
    if not connection or not connection["is_enabled"]:
        return

    await db.log_message(
        connection["connection_id"], message.chat.id, message.message_id
    )

    disabled = await db.list_disabled_modules(connection["connection_id"])
    is_owner = message.from_user.id == connection["owner_id"]

    text_for_history = message.text or message.caption
    media_type, media_data = (None, None)
    if "archive" not in disabled:
        try:
            media_type, media_data = await extract_history_media(bot, message)
        except Exception:
            # get_file/download могут упасть (файл >20 МБ, сетевая ошибка) —
            # это не должно ронять обработку сообщения и команды
            logger.warning(
                "Не удалось скачать медиа сообщения %s", message.message_id,
                exc_info=True,
            )

    if "archive" not in disabled and is_owner and message.reply_to_message is not None:
        existing = await db.get_history_entry(
            connection["connection_id"],
            message.chat.id,
            message.reply_to_message.message_id,
        )
        if existing is None:
            try:
                rescued_type, rescued_data = await extract_media_from_reply(
                    bot, message
                )
            except Exception:
                logger.warning(
                    "Не удалось достать медиа из reply_to_message %s",
                    message.reply_to_message.message_id,
                    exc_info=True,
                )
                rescued_type, rescued_data = None, None
            # Диагностика: что именно Telegram положил в reply_to_message.
            # Для самоуничтожающегося медиа Bot API не отдаёт файл, и тогда
            # здесь будет пусто — это видно по списку полей.
            logger.info(
                "rescue: reply_to=%s нет в истории; поля=%s; медиа=%s",
                message.reply_to_message.message_id,
                sorted(message.reply_to_message.model_fields_set),
                rescued_type,
            )
            if rescued_type is not None:
                await db.save_history(
                    connection["connection_id"],
                    message.chat.id,
                    message.reply_to_message.message_id,
                    False,
                    None,
                    int(message.reply_to_message.date.timestamp()),
                    media_type=rescued_type,
                    media_data=rescued_data,
                )

    if text_for_history is not None or media_type is not None:
        await db.save_history(
            connection["connection_id"],
            message.chat.id,
            message.message_id,
            is_owner,
            text_for_history,
            int(message.date.timestamp()) if message.date else int(time.time()),
            media_type=media_type,
            media_data=media_data,
        )

    if is_owner and message.voice and "voice" not in disabled:
        if await handle_voice_message(bot, connection, message):
            return

    if not is_owner:
        if "scam" not in disabled:
            await handle_new_contact(bot, connection, message)
        else:
            # known_chats нужен и вебаппу (аватарки/имена собеседников),
            # поэтому помечаем контакт, даже если модуль scam выключен
            await db.mark_known_chat(connection["owner_id"], message.chat.id)

        if "mute" not in disabled and await handle_mute_incoming(
            bot, connection, message
        ):
            return

        if "echo" not in disabled and await db.is_echo_enabled(
            connection["connection_id"], message.chat.id
        ):
            text = message.text or message.caption
            if text:
                sent = await bot.send_message(
                    business_connection_id=connection["connection_id"],
                    chat_id=message.chat.id,
                    text=text,
                )
                await db.log_message(
                    connection["connection_id"], message.chat.id, sent.message_id
                )
            return

    text = message.text or message.caption
    if not text:
        return

    for trigger in TYPE_TRIGGERS:
        if text.startswith(trigger):
            if is_owner and "type" not in disabled:
                await handle_type_trigger(bot, message, connection, trigger)
            return

    prefix = connection["prefix"]
    if not text.startswith(prefix):
        return

    body = text[len(prefix) :].strip()
    if not body:
        return

    parts = body.split(maxsplit=1)
    alias = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    cmd = registry.find(alias)
    if not cmd:
        # пользовательский алиас владельца (добавляется в вебаппе)
        custom_target = await db.get_command_alias(connection["owner_id"], alias)
        if custom_target:
            cmd = registry.find(custom_target)
    if not cmd:
        if "wordle" not in disabled:
            locale = await db.get_locale(connection["owner_id"])
            await handle_wordle_guess(bot, connection, message, locale, alias)
        return

    if cmd.module in disabled:
        return

    if cmd.owner_only and not is_owner:
        return

    ctx = CommandContext(
        bot=bot,
        message=message,
        connection=connection,
        args=args,
        locale=await db.get_locale(connection["owner_id"]),
    )
    await cmd.handler(ctx)
