"""Обработчик правок: уведомление (Rich или обычное), журнал, обновление истории."""

import time

from aiogram import Bot, Router
from aiogram.types import Message

from app.features.archive import service
from app.features.history.adapter import build_snapshot
from app.features.archive.bot import send_classic, send_rich
from app.features.archive.bot.keyboards import link_keyboard
from app.features.archive.prefs import defaults
from app.features.archive.service import TEXT_EDITS
from app.platform.telegram.mentions import format_mention
from app.platform.telegram.self_actions import is_bot_edit
from app.platform.utils import log_suppressed
from db.models.connection import get_connection
from db.models.user_locale import get_locale

router = Router(name="archive_edited")


async def notify_edited(
    bot,
    connection,
    message,
    locale,
    mention,
    change,
    old,
    old_entry,
    new,
    previous=(),
    prefs=None,
):
    """Уведомление об изменении. Возвращает id сообщения-уведомления (или None)."""
    prefs = prefs or defaults()
    chat_id = connection["owner_chat_id"]
    link_kb = link_keyboard(
        locale, getattr(message.chat, "username", None), message.message_id
    )

    if prefs.rich and change in TEXT_EDITS[:3]:
        # без истории каждая правка — отдельное уведомление
        previous = previous if prefs.edit_history else []
        albums = await service.album_entries(
            connection["connection_id"], message.chat.id, new
        )
        notice_id = await send_rich.try_edit_history(
            bot,
            chat_id,
            message.message_id,
            locale,
            mention,
            change,
            old,
            new,
            previous,
            link_kb,
            (old_entry or {}).get("created_at"),
            prefs,
            albums,
            service.last_notice_id(previous),
            int(time.time()),
        )
        if notice_id:
            return notice_id

    if change == "text":
        return await send_classic.edited_text(
            bot, chat_id, locale, mention, old, new, link_kb
        )
    if change in ("caption", "caption_removed"):
        return await send_classic.edited_caption(
            bot, chat_id, locale, mention, old, new, link_kb
        )

    notice_id = await send_rich.try_edited_media(
        bot, chat_id, locale, mention, change, old, old_entry, new, prefs, link_kb
    )
    if notice_id:
        return notice_id
    return await send_classic.edited_media(
        bot, chat_id, locale, mention, change, old, old_entry, new, link_kb
    )


@router.edited_business_message()
async def on_business_edited(message: Message, bot: Bot):
    connection_id = message.business_connection_id
    if not await service.is_enabled(connection_id):
        return
    snap = build_snapshot(message, bot_id=getattr(bot, "id", None))
    if snap is None:
        return
    connection = await get_connection(connection_id)
    if not connection:
        return

    chat_id, message_id = message.chat.id, message.message_id
    plan = await service.plan_edit(
        connection,
        chat_id,
        message_id,
        message.from_user.id,
        snap,
        bot_edit=is_bot_edit(connection_id, chat_id, message_id),
    )
    notice_id = None
    if plan.notify:
        try:
            notice_id = await notify_edited(
                bot,
                connection,
                message,
                await get_locale(connection["owner_id"]),
                format_mention(
                    message.from_user.full_name, message.from_user.username, chat_id
                ),
                plan.change,
                plan.old,
                plan.old_entry,
                snap,
                await service.previous_edits(connection_id, chat_id, message_id),
                plan.prefs,
            )
        except Exception:
            log_suppressed("archive/bot/edited.py:notify_edited")
    await service.record_edit(connection_id, chat_id, message_id, plan, snap, notice_id)
