import time
from difflib import SequenceMatcher
from html import escape

from aiogram import Bot, F, Router, html
from aiogram.types import (
    BufferedInputFile,
    BusinessMessagesDeleted,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    LinkPreviewOptions,
)

from core import database as db
from core.i18n import t
from core.registry import registry
from core.self_actions import consume_self_delete

router = Router(name="archive")
registry.register_passive_module("archive")

_MEDIA_LABEL_KEYS = {
    "photo": "archive.media_photo",
    "video": "archive.media_video",
    "voice": "archive.media_voice",
    "video_note": "archive.media_video_note",
}


def highlight_changes(old_text: str, new_text: str) -> str:
    matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)

    result = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        new_part = new_text[j1:j2]

        if tag == "equal":
            result.append(escape(new_part))

        elif tag in ("replace", "insert"):
            if new_part:
                result.append(f"<b>{escape(new_part)}</b>")

    return "".join(result)


def _format_mention(full_name, username, chat_id):
    if username:
        return f'<a href="https://t.me/{username}">{html.quote(full_name)}</a>'
    return f'<a href="tg://user?id={chat_id}">{html.quote(full_name)}</a>'


def _message_link(username, message_id):
    if not username:
        return None
    return f"https://t.me/{username}/{message_id}"


def _link_keyboard(locale, username, message_id):
    label = t("archive.open_message_button", locale)
    link = _message_link(username, message_id)
    if link:
        button = InlineKeyboardButton(
            text=label, url=link, icon_custom_emoji_id="5260730055880876557"
        )
    else:
        button = InlineKeyboardButton(
            text=label,
            callback_data="archive:link_unavailable",
            icon_custom_emoji_id="5260730055880876557",
        )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


async def _send_deleted_media(bot, chat_id, entry, locale):
    kind = entry.get("media_type")
    data = entry.get("media_data")
    if not kind or not data:
        return
    method_name, kwarg = _MEDIA_SEND[kind]
    file = BufferedInputFile(bytes(data), filename=f"deleted_{kind}")
    caption = t(_MEDIA_LABEL_KEYS.get(kind, "archive.media_placeholder"), locale)
    try:
        await getattr(bot, method_name)(chat_id=chat_id, caption=caption, **{kwarg: file})
    except Exception:
        pass


@router.callback_query(F.data == "archive:link_unavailable")
async def on_link_unavailable(call: CallbackQuery):
    locale = await db.get_locale(call.from_user.id)
    await call.answer(t("archive.link_unavailable", locale), show_alert=True)


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
            text = t(
                "archive.edited_notice",
                locale,
                mention=_format_mention(
                    message.from_user.full_name,
                    message.from_user.username,
                    message.chat.id,
                ),
                old_text=html.quote(old_text),
                new_text=highlight_changes(old_text, new_text),
            )
            try:
                await bot.send_message(
                    chat_id=connection["owner_chat_id"],
                    text=text,
                    reply_markup=_link_keyboard(
                        locale, message.chat.username, message.message_id
                    ),
                    link_preview_options=LinkPreviewOptions(is_disabled=True),
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

        body = (
            html.quote(entry["text"])
            if entry["text"]
            else t("archive.media_placeholder", locale)
        )
        text = t(
            "archive.deleted_notice",
            locale,
            mention=_format_mention(
                event.chat.full_name, event.chat.username, event.chat.id
            ),
            old_text=body,
        )

        try:
            await bot.send_message(
                chat_id=connection["owner_chat_id"],
                text=text,
                link_preview_options=LinkPreviewOptions(is_disabled=True),
            )
        except Exception:
            pass

        await _send_deleted_media(bot, connection["owner_chat_id"], entry, locale)

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
