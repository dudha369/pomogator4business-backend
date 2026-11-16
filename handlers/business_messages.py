import asyncio
import logging
import time
from dataclasses import dataclass, field

from aiogram import Bot, Router
from aiogram.types import Message

from config import settings
from db.models.command_alias import get_command_alias
from db.models.connection import get_connection
from db.models.echo import is_echo_enabled
from db.models.known_chat import mark_known_chat
from db.models.message_history import (
    get_history_entry,
    save_history,
    set_history_transcript,
)
from db.models.message_log import log_message
from db.models.module_settings import list_disabled_modules
from db.models.user_locale import get_locale
from app.features.archive.prefs import load_prefs
from core.autoresponder import handle_incoming as handle_autoresponder
from app.platform.telegram.context import CommandContext
from app.platform.i18n import t
from app.platform.media import extract_history_media, extract_media_from_reply
from app.platform.telegram.registry import registry
from app.features.archive.adapter import build_snapshot
from app.platform.tasks import spawn
from core.utils import log_suppressed
from app.features.mute.bot import handle_incoming as handle_mute_incoming
from commands.scam import handle_new_contact
from commands.type_ import TYPE_TRIGGERS, handle_type_trigger
from commands.voice_effects import handle_voice_message
from app.features.games.bot.wordle import handle_wordle_guess

logger = logging.getLogger("bot.business_messages")
router = Router(name="business_messages")


@dataclass
class Incoming:
    bot: Bot
    message: Message
    connection: dict
    disabled: set = field(default_factory=set)
    is_owner: bool = False

    @property
    def connection_id(self) -> str:
        return self.connection["connection_id"]

    @property
    def chat_id(self) -> int:
        return self.message.chat.id

    @property
    def text(self):
        return self.message.text or self.message.caption

    def enabled(self, module: str) -> bool:
        return module not in self.disabled


def _media_fields(media):
    if media is None:
        return {}
    return {
        "media_type": media.kind,
        "media_data": media.data,
        "media_mime": media.mime,
        "media_name": media.name,
        "media_status": media.status,
    }


_VOICE_MAX_SECONDS = 120


async def _transcribe_into_history(bot, connection_id, chat_id, message_id, voice):
    """Распознаёт голосовое и дописывает текст в историю (в фоне: распознавание
    занимает секунды, а цепочка обработки сообщения ждать не должна)."""
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


async def step_history(inc: Incoming) -> bool:
    message, connection_id = inc.message, inc.connection_id
    snapshot = build_snapshot(message, bot_id=getattr(inc.bot, "id", None))
    media = None

    if inc.enabled("archive") and settings.KEEP_MEDIA_BYTES:
        try:
            media = await extract_history_media(inc.bot, message)
        except Exception:
            logger.warning(
                "Ошибка извлечения медиа сообщения %s",
                message.message_id,
                exc_info=True,
            )

    if inc.enabled("archive") and inc.is_owner and message.reply_to_message is not None:
        await _rescue_replied_media(inc)

    if inc.text is not None or snapshot is not None:
        await save_history(
            connection_id,
            inc.chat_id,
            message.message_id,
            inc.is_owner,
            inc.text,
            int(message.date.timestamp()) if message.date else int(time.time()),
            snapshot=snapshot,
            **_media_fields(media),
        )

    voice = getattr(message, "voice", None)
    if (
        voice is not None
        and not inc.is_owner
        and inc.enabled("archive")
        and (getattr(voice, "duration", 0) or 0) <= _VOICE_MAX_SECONDS
        and (await load_prefs(connection_id)).voice_transcript
    ):
        spawn(
            _transcribe_into_history(
                inc.bot, connection_id, inc.chat_id, message.message_id, voice
            )
        )
    return False


async def _rescue_replied_media(inc: Incoming) -> None:
    """Владелец ответил на сообщение, которого нет в истории (так выглядит исчезающее
    медиа: отдельным апдейтом оно не приходит). Достаём файл из reply_to_message сейчас,
    пока Telegram его туда вкладывает, и сохраняем БАЙТАМИ: file_id такого медиа может
    перестать работать, поэтому полагаться на него нельзя."""
    message, replied = inc.message, inc.message.reply_to_message
    existing = await get_history_entry(
        inc.connection_id, inc.chat_id, replied.message_id
    )
    if existing is not None:
        return

    try:
        rescued = await extract_media_from_reply(inc.bot, message)
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
            **_media_fields(rescued),
        )


async def step_voice(inc: Incoming) -> bool:
    if inc.is_owner and inc.message.voice and inc.enabled("voice"):
        return bool(await handle_voice_message(inc.bot, inc.connection, inc.message))
    return False


async def step_new_contact(inc: Incoming) -> bool:
    if inc.is_owner:
        return False
    if inc.enabled("scam"):
        await handle_new_contact(inc.bot, inc.connection, inc.message)
    else:
        await mark_known_chat(inc.connection["owner_id"], inc.chat_id)
    return False


async def step_mute(inc: Incoming) -> bool:
    if inc.is_owner or not inc.enabled("mute"):
        return False
    return bool(await handle_mute_incoming(inc.bot, inc.connection, inc.message))


async def step_autoresponder(inc: Incoming) -> bool:
    if inc.is_owner:
        return False
    try:
        await handle_autoresponder(inc.bot, inc.connection, inc.message)
    except Exception:
        logger.exception("Сбой автоответчика")
    return False


async def step_echo(inc: Incoming) -> bool:
    if inc.is_owner or not inc.enabled("echo"):
        return False
    if not await is_echo_enabled(inc.connection_id, inc.chat_id):
        return False
    if inc.text:
        sent = await inc.bot.send_message(
            business_connection_id=inc.connection_id,
            chat_id=inc.chat_id,
            text=inc.text,
        )
        await log_message(inc.connection_id, inc.chat_id, sent.message_id)
    return True


async def step_type_trigger(inc: Incoming) -> bool:
    if not inc.text:
        return True
    for trigger in TYPE_TRIGGERS:
        if inc.text.startswith(trigger):
            if inc.is_owner and inc.enabled("type"):
                await handle_type_trigger(inc.bot, inc.message, inc.connection, trigger)
            return True
    return False


async def step_command(inc: Incoming) -> bool:
    prefix = inc.connection["prefix"]
    if not inc.text.startswith(prefix):
        return True

    body = inc.text[len(prefix) :].strip()
    if not body:
        return True

    parts = body.split(maxsplit=1)
    alias = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    cmd = registry.find(alias)
    if not cmd:
        custom_target = await get_command_alias(inc.connection["owner_id"], alias)
        if custom_target:
            cmd = registry.find(custom_target)
    if not cmd:
        if inc.enabled("wordle"):
            locale = await get_locale(inc.connection["owner_id"])
            await handle_wordle_guess(
                inc.bot, inc.connection, inc.message, locale, alias
            )
        return True

    if cmd.module in inc.disabled or (cmd.owner_only and not inc.is_owner):
        return True

    ctx = CommandContext(
        bot=inc.bot,
        message=inc.message,
        connection=inc.connection,
        args=args,
        locale=await get_locale(inc.connection["owner_id"]),
    )
    try:
        await cmd.handler(ctx)
    except Exception:
        # команду часто удаляют ДО выполнения: без этого при сбое она исчезает молча
        logger.exception("Сбой команды %s", cmd.name)
        await _report_command_failure(inc, cmd.name, ctx.locale)
    return True


_FAILURE_NOTICE_INTERVAL = 60
_last_failure_notice: dict[tuple[str, str], float] = {}


async def _report_command_failure(inc: Incoming, name: str, locale: str) -> None:
    """Сообщить владельцу, что команда не выполнилась (не чаще раза в минуту на команду)."""
    key, now = (inc.connection_id, name), time.monotonic()
    if (
        now - _last_failure_notice.get(key, -_FAILURE_NOTICE_INTERVAL)
        < _FAILURE_NOTICE_INTERVAL
    ):
        return
    _last_failure_notice[key] = now
    try:
        await inc.bot.send_message(
            chat_id=inc.connection["owner_chat_id"],
            text=t("cmd.failed", locale, name=name),
            parse_mode=None,
        )
    except Exception:
        log_suppressed("handlers/business_messages.py:report_failure", benign=True)


PIPELINE = (
    step_history,
    step_voice,
    step_new_contact,
    step_mute,
    step_autoresponder,
    step_echo,
    step_type_trigger,
    step_command,
)


async def run_pipeline(inc: Incoming, steps=PIPELINE) -> None:
    for step in steps:
        if await step(inc):
            return


@router.business_message()
async def on_business_message(message: Message, bot: Bot):
    connection = await get_connection(message.business_connection_id)
    if not connection or not connection["is_enabled"]:
        return

    is_owner = message.from_user.id == connection["owner_id"]
    if is_owner:
        # журнал нужен только для .del/.panic — они трогают сообщения владельца
        await log_message(
            connection["connection_id"], message.chat.id, message.message_id
        )

    await run_pipeline(
        Incoming(
            bot=bot,
            message=message,
            connection=connection,
            disabled=await list_disabled_modules(connection["connection_id"]),
            is_owner=is_owner,
        )
    )
