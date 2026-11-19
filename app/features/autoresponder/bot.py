import logging
import time

from app.features.ai import bot as ai_bot
from app.features.ai import service as ai
from app.features.ai.queries import get_ai_settings
from app.features.alerts.bot import report
from app.features.autoresponder.queries import (
    get_autoresponder_settings,
    last_autoreply_at,
    list_keyword_replies,
    log_autoreply,
)
from app.features.autoresponder.service import (
    AWAY_COOLDOWN_SECONDS,
    KEYWORD_COOLDOWN_SECONDS,
    MAX_REPLY_LENGTH,
    NO_SETTINGS,
    OWNER_ACTIVE_WINDOW_SECONDS,
    AutoReply,
    build_candidates,
)
from app.features.chats.queries import get_chat_flags, is_favorite_chat
from app.features.history.service import (
    has_other_messages,
    last_owner_message_at,
    log_message,
)
from db.models.user_locale import get_timezone_offset

logger = logging.getLogger("bot.autoresponder")


# ------------------------------ оркестратор --------------------------------


async def _cooldown_ok(owner_id, chat_id, reply: AutoReply, now: int) -> bool:
    last = await last_autoreply_at(owner_id, chat_id, reply.kind, reply.ref)
    if last is None:
        return True
    if reply.kind == "greeting":
        return False  # приветствие — один раз навсегда
    window = AWAY_COOLDOWN_SECONDS if reply.kind == "away" else KEYWORD_COOLDOWN_SECONDS
    return now - last >= window


async def _auto_read(bot, connection, message):
    try:
        if await is_favorite_chat(connection["owner_id"], message.chat.id):
            return  # избранные чаты остаются непрочитанными — это их смысл
        await bot.read_business_message(
            business_connection_id=connection["connection_id"],
            chat_id=message.chat.id,
            message_id=message.message_id,
        )
    except Exception:
        logger.warning("auto-read chat=%s", message.chat.id, exc_info=True)


async def handle_incoming(bot, connection, message, now=None) -> AutoReply | None:
    """Вызывается для входящего (не от владельца) сообщения. Возвращает
    отправленный автоответ или None.
    Любые сбои логируются и не прерывают обработку сообщения."""
    user = message.from_user
    if (
        user is None
        or user.is_bot
        or getattr(message.chat, "type", "private") != "private"
    ):
        return None

    owner_id = connection["owner_id"]
    # строки настроек может не быть (например, включён только ИИ) — берём «всё выключено»
    settings = await get_autoresponder_settings(owner_id) or NO_SETTINGS

    if settings["auto_read_enabled"]:
        await _auto_read(bot, connection, message)

    chat_id = message.chat.id
    flags = await get_chat_flags(owner_id, chat_id)
    if flags["no_autoreply"]:
        return None  # чат в режиме «не беспокоить» (авто-прочтение выше — по своей настройке)

    text = message.text or message.caption or ""
    is_command = bool(text) and text.startswith(connection["prefix"])

    keywords = await list_keyword_replies(owner_id) if text and not is_command else []
    ai_settings = await get_ai_settings(owner_id)
    if ai_settings and ai_settings["enabled"] and not ai.is_configured():
        await report(owner_id, "ai_no_key")
    ai_on = bool(
        ai_settings
        and ai_settings["enabled"]
        and ai.is_configured()
        and text
        and not is_command
        and not flags["no_ai"]
    )
    if not (
        settings["greeting_enabled"] or settings["away_enabled"] or keywords or ai_on
    ):
        return None

    now = int(now if now is not None else time.time())
    last_owner_at = await last_owner_message_at(connection["connection_id"], chat_id)
    # «новый собеседник»: ни владелец, ни он сам раньше в этом чате не писали
    # (по сохранённой истории) и приветствия ему ещё не отправлялись
    is_new_contact = last_owner_at is None and not await has_other_messages(
        connection["connection_id"], chat_id, message.message_id
    )
    owner_recently_active = (
        last_owner_at is not None and now - last_owner_at < OWNER_ACTIVE_WINDOW_SECONDS
    )

    candidates = build_candidates(
        settings=settings,
        keywords=keywords,
        text=text,
        is_command=is_command,
        is_new_contact=is_new_contact,
        owner_recently_active=owner_recently_active,
        now=now,
        tz_offset=await get_timezone_offset(owner_id),
        user=user,
    )

    for reply in candidates:
        if not await _cooldown_ok(owner_id, chat_id, reply, now):
            continue
        try:
            sent = await bot.send_message(
                business_connection_id=connection["connection_id"],
                chat_id=chat_id,
                text=reply.text[:MAX_REPLY_LENGTH],
            )
        except Exception:
            logger.warning(
                "Не удалось отправить автоответ chat=%s", chat_id, exc_info=True
            )
            return None

        await log_message(connection["connection_id"], chat_id, sent.message_id)
        await log_autoreply(owner_id, chat_id, reply.kind, reply.ref, now)
        if is_new_contact and reply.kind != "greeting":
            # первое сообщение уже получило ответ — приветствовать задним числом не нужно
            await log_autoreply(owner_id, chat_id, "greeting", None, now)
        return reply

    # Ничего из «правил» не подошло — последний рубеж: ИИ (если включён)
    if ai_on and not owner_recently_active:
        try:
            reply_text = await ai.generate_reply(
                connection, ai_settings, chat_id, message, text, now
            )
            if reply_text and await ai_bot.deliver_reply(
                bot, connection, ai_settings, message, text, reply_text, now
            ):
                return AutoReply("ai", None, reply_text)
        except Exception:
            logger.warning("Сбой ИИ-ответа chat=%s", chat_id, exc_info=True)

    return None


async def autoresponder_step(handler, message, data):
    """Middleware: автоответ собеседнику; сбой не прерывает обработку сообщения."""
    inc = data["inc"]
    if not inc.is_owner:
        try:
            await handle_incoming(inc.bot, inc.connection, inc.message)
        except Exception:
            logger.exception("Сбой автоответчика")
    return await handler(message, data)
