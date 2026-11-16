"""Обработчик удалённых сообщений: решает, как показать (Rich или обычно), и пишет журнал."""

from aiogram import Bot, Router
from aiogram.types import BusinessMessagesDeleted

from app.features.archive import service
from app.features.archive.bot import send_classic, send_rich
from app.features.archive.bot.keyboards import delete_keyboard
from app.features.archive.prefs import load_prefs
from core.mentions import format_mention
from core.self_actions import consume_self_delete
from core.utils import log_suppressed
from db.models.connection import get_connection
from db.models.user_locale import get_locale

router = Router(name="archive_deleted")


async def notify_deleted(
    bot, chat_id, locale, mention, sender, snap, entry, prefs, own=False
):
    header_key = service.deleted_header_key(own)
    markup = delete_keyboard(locale)
    if await send_rich.try_deleted(
        bot, chat_id, locale, mention, snap, entry, prefs, header_key, markup
    ):
        return
    await send_classic.deleted(
        bot, chat_id, locale, mention, sender, snap, entry, header_key, own
    )


async def notify_album(bot, chat_id, locale, mention, sender, items, prefs, own=False):
    """Весь удалённый альбом одним уведомлением (items — [(снимок, запись)])."""
    header_key = service.deleted_header_key(own)
    if await send_rich.try_album(
        bot,
        chat_id,
        locale,
        mention,
        items,
        prefs,
        header_key,
        delete_keyboard(locale),
    ):
        return
    leftovers = await send_classic.album(
        bot, chat_id, locale, mention, items, header_key
    )
    for snap, entry in leftovers:
        await notify_deleted(
            bot, chat_id, locale, mention, sender, snap, entry, prefs, own
        )


@router.deleted_business_messages()
async def on_business_deleted(event: BusinessMessagesDeleted, bot: Bot):
    connection_id = event.business_connection_id
    if not await service.is_enabled(connection_id):
        return
    connection = await get_connection(connection_id)
    if not connection:
        return

    chat = event.chat
    locale = await get_locale(connection["owner_id"])
    mention = format_mention(chat.full_name, chat.username, chat.id)
    prefs = await load_prefs(connection_id)
    sender = {
        "id": chat.id,
        "username": getattr(chat, "username", None),
        "name": chat.full_name,
    }
    found = await service.collect_deleted(
        connection_id,
        chat.id,
        event.message_ids,
        lambda message_id: consume_self_delete(connection_id, chat.id, message_id),
    )

    for unit in service.group_albums(found):
        own = bool(unit[0][1]["is_owner"])  # альбом — всегда одного автора
        owner_chat = connection["owner_chat_id"]
        try:
            if len(unit) == 1:
                _, entry, snap = unit[0]
                await notify_deleted(
                    bot, owner_chat, locale, mention, sender, snap, entry, prefs, own
                )
            else:
                items = [(snap, entry) for _, entry, snap in unit]
                await notify_album(
                    bot, owner_chat, locale, mention, sender, items, prefs, own
                )
        except Exception:
            log_suppressed("archive/bot/deleted.py:notify_deleted")
        await service.record_deleted(connection_id, chat.id, unit, own)
