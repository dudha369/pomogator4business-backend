import time

from aiogram import Bot, Router, html
from aiogram.types import BusinessMessagesDeleted, Message

from core import database as db
from core.i18n import t
from core.registry import registry
from core.self_actions import consume_self_delete

router = Router(name="archive")
registry.register_passive_module("archive")


def _format_mention(full_name, username, chat_id):
    if username:
        return f'<a href="https://t.me/{username}">{full_name}</a>'

    return f'<a href="tg://user?id={chat_id}">{full_name}</a>'


def _format_edited(locale, old_text, new_text, sender_label):
    return t(
        "archive.edited_notice",
        locale,
        sender=sender_label,
        old_text=old_text,
        new_text=new_text,
    )


def _format_deleted(locale, old_text, sender_label):
    return t("archive.deleted_notice", locale, sender=sender_label, old_text=old_text)


@router.edited_business_message()
async def on_business_edited(message: Message, bot: Bot):
    connection_id = message.business_connection_id
    disabled = await db.list_disabled_modules(connection_id)
    if "archive" in disabled:
        return

    new_text = message.text or message.caption
    if new_text is None:
        return

    connection = await db.get_connection(connection_id)
    if not connection:
        return

    is_owner = message.from_user.id == connection["owner_id"]

    if not is_owner:
        old_text = await db.get_history_text(
            connection_id, message.chat.id, message.message_id
        )
        if old_text is not None and old_text != new_text:
            locale = await db.get_locale(connection["owner_id"])
            try:
                await bot.send_message(
                    chat_id=connection["owner_chat_id"],
                    text=_format_edited(
                        locale,
                        old_text,
                        new_text,
                        _format_mention(
                            message.from_user.full_name,
                            message.from_user.username,
                            message.chat.id,
                        ),
                    ),
                    parse_mode="html",
                )
            except Exception:
                pass

            await db.log_archive_event(
                connection_id,
                message.chat.id,
                message.message_id,
                "edited",
                old_text,
                new_text,
                int(time.time()),
            )

    await db.save_history(
        connection_id,
        message.chat.id,
        message.message_id,
        is_owner,
        new_text,
        int(time.time()),
    )


@router.deleted_business_messages()
async def on_business_deleted(event: BusinessMessagesDeleted, bot: Bot):
    connection_id = event.business_connection_id
    disabled = await db.list_disabled_modules(connection_id)
    if "archive" in disabled:
        return

    connection = await db.get_connection(connection_id)
    if not connection:
        return

    locale = await db.get_locale(connection["owner_id"])

    for message_id in event.message_ids:
        if consume_self_delete(connection_id, event.chat.id, message_id):
            await db.delete_history(connection_id, event.chat.id, message_id)
            continue

        entry = await db.get_history_entry(connection_id, event.chat.id, message_id)
        if entry is None:
            continue

        sender_label = (
            t("archive.sender_you", locale)
            if entry["is_owner"]
            else _format_mention(
                event.chat.full_name, event.chat.username, event.chat.id
            )
        )

        try:
            await bot.send_message(
                chat_id=connection["owner_chat_id"],
                text=_format_deleted(locale, entry["text"], sender_label),
                parse_mode="html",
            )
        except Exception:
            pass

        await db.log_archive_event(
            connection_id,
            event.chat.id,
            message_id,
            "deleted",
            entry["text"],
            None,
            int(time.time()),
        )
        await db.delete_history(connection_id, event.chat.id, message_id)
