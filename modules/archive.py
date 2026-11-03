import logging
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
    LinkPreviewOptions,
    Message,
    ReplyParameters,
)

from core import database as db
from core.archive_notice import (
    CAPTION_LIMIT,
    MESSAGE_LIMIT,
    build_notice,
)
from core.i18n import t
from core.mentions import format_mention
from core.registry import registry
from core.self_actions import consume_self_delete
from core.snapshot import FILE_KINDS, build_snapshot, edit_kind, entry_snapshot
from core.utils import log_suppressed

logger = logging.getLogger("bot.archive")
router = Router(name="archive")
registry.register_passive_module("archive")

_CAPTIONABLE = {
    "photo": ("send_photo", "photo"),
    "video": ("send_video", "video"),
    "animation": ("send_animation", "animation"),
    "voice": ("send_voice", "voice"),
    "audio": ("send_audio", "audio"),
    "document": ("send_document", "document"),
}
_CAPTION_ABOVE = {"photo", "video", "animation"}
_NO_CAPTION = {
    "sticker": ("send_sticker", "sticker"),
    "video_note": ("send_video_note", "video_note"),
}
_RESENDABLE_DATA = {"location", "venue", "contact"}
_CLIP = 1700


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
            icon_custom_emoji_id="5260730055880876557",
            callback_data="archive:link_unavailable",
        )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def _delete_button_keyboard(locale, callback="archive:delete_notice"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("archive.delete_notice_button", locale),
                    icon_custom_emoji_id="5258130763148172425",
                    callback_data=callback,
                )
            ]
        ]
    )


def _file_input(entry, snap):
    """Что передать в send_*: байты (если мы их сохраняли) или file_id."""
    data = (entry or {}).get("media_data")
    if data:
        return BufferedInputFile(
            bytes(data), filename=snap.get("media_name") or f"deleted_{snap['kind']}"
        )
    return snap.get("file_id")


async def _send_media(
    bot, chat_id, snap, file, *, caption=None, above=True, reply_to=None, markup=None
):
    """Отправляет сохранённое содержимое (файл, геолокацию, контакт)."""
    kind = snap["kind"]
    extra = {}
    if reply_to is not None:
        extra["reply_parameters"] = ReplyParameters(message_id=reply_to)
    if markup is not None:
        extra["reply_markup"] = markup
    payload = snap.get("payload") or {}

    if kind in _CAPTIONABLE:
        method, arg = _CAPTIONABLE[kind]
        if caption:
            extra["caption"] = caption
            if kind in _CAPTION_ABOVE and above:
                extra["show_caption_above_media"] = True
        if kind in _CAPTION_ABOVE and snap.get("has_spoiler"):
            extra["has_spoiler"] = True
        return await getattr(bot, method)(chat_id=chat_id, **{arg: file}, **extra)
    if kind in _NO_CAPTION:
        method, arg = _NO_CAPTION[kind]
        return await getattr(bot, method)(chat_id=chat_id, **{arg: file}, **extra)
    if kind == "location":
        return await bot.send_location(
            chat_id=chat_id,
            latitude=payload["latitude"],
            longitude=payload["longitude"],
            **extra,
        )
    if kind == "venue":
        loc = payload.get("location") or {}
        return await bot.send_venue(
            chat_id=chat_id,
            latitude=loc["latitude"],
            longitude=loc["longitude"],
            title=payload.get("title") or "",
            address=payload.get("address") or "",
            **extra,
        )
    if kind == "contact":
        return await bot.send_contact(
            chat_id=chat_id,
            phone_number=payload["phone_number"],
            first_name=payload.get("first_name") or "",
            last_name=payload.get("last_name"),
            **extra,
        )
    raise ValueError(f"нечего отправлять для типа {kind}")


async def _notify_deleted(bot, chat_id, locale, mention, snap, entry):
    """Уведомление об удалённом сообщении.

    Медиа с подписью (фото, видео, GIF, голосовое, аудио, файл) — ОДНО сообщение:
    подпись (сверху, где Telegram это позволяет) + кнопка «Удалить у себя».
    Стикер, кружок, геолокация, контакт: сначала сообщение-уведомление, затем само
    содержимое ответом на него с кнопкой (она удаляет обе части)."""
    kind = snap["kind"]
    is_file = kind in FILE_KINDS
    file = _file_input(entry, snap) if is_file else None
    send_failed = False
    delete_one = _delete_button_keyboard(locale)

    if kind in _CAPTIONABLE and file:
        caption = build_notice(locale, mention, snap, limit=CAPTION_LIMIT)
        try:
            await _send_media(
                bot, chat_id, snap, file, caption=caption, markup=delete_one
            )
            return
        except Exception:
            logger.exception("Не удалось отправить сохранённое медиа (%s)", kind)
            send_failed = True

    detail = kind != "text" and not is_file
    text = build_notice(locale, mention, snap, limit=MESSAGE_LIMIT - 100, detail=detail)
    follow_up = (kind in _NO_CAPTION and file) or kind in _RESENDABLE_DATA
    if is_file and (not file or send_failed):
        text += "\n\n" + t("archive.media_unavailable", locale)

    notice = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=None if follow_up else delete_one,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    if not follow_up:
        return
    try:
        await _send_media(
            bot,
            chat_id,
            snap,
            file,
            reply_to=notice.message_id,
            markup=_delete_button_keyboard(locale, "archive:delete_pair"),
        )
    except Exception:
        logger.exception("Не удалось отправить сохранённое содержимое (%s)", kind)
        try:  # уведомление всё равно должно быть удаляемым
            await bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=notice.message_id, reply_markup=delete_one
            )
        except Exception:
            log_suppressed("modules/archive.py:notice_markup", benign=True)


def _clip(text):
    text = text or ""
    return text if len(text) <= _CLIP else text[:_CLIP].rstrip() + "…"


def _before_after(locale, old_text, new_text):
    old_html = escape(_clip(old_text)) or t("archive.empty_text", locale)
    new_html = (
        highlight_changes(_clip(old_text), _clip(new_text))
        if new_text
        else t("archive.empty_text", locale)
    )
    return (
        f"\n\n{t('archive.caption_before', locale)}\n"
        f"<blockquote expandable>{old_html}</blockquote>\n\n"
        f"{t('archive.caption_after', locale)}\n"
        f"<blockquote expandable>{new_html}</blockquote>"
    )


async def _notify_edited(
    bot, connection, message, locale, mention, change, old, old_entry, new
):
    chat_id = connection["owner_chat_id"]
    link_kb = _link_keyboard(
        locale, getattr(message.chat, "username", None), message.message_id
    )
    no_preview = LinkPreviewOptions(is_disabled=True)

    if change == "text":
        text = t(
            "archive.edited_notice",
            locale,
            mention=mention,
            old_text=html.quote(old["text"] or ""),
            new_text=highlight_changes(old["text"] or "", new["text"] or ""),
        )
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=link_kb,
            link_preview_options=no_preview,
        )
        return

    if change in ("caption", "caption_removed"):
        header = t("archive.edited_caption_header", locale, mention=mention)
        text = header + _before_after(locale, old["text"], new["text"])
        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=link_kb,
            link_preview_options=no_preview,
        )
        return

    # media / media_caption: уведомление, затем «было» и «стало» ответами на него
    text = t("archive.edited_media_header", locale, mention=mention)
    if change == "media_caption":
        text += _before_after(locale, old["text"], new["text"])
    notice = await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=link_kb,
        link_preview_options=no_preview,
    )
    for snap, entry, label in (
        (old, old_entry, "archive.caption_before"),
        (new, None, "archive.caption_after"),
    ):
        file = _file_input(entry, snap)
        if not file:
            continue
        try:
            await _send_media(
                bot,
                chat_id,
                snap,
                file,
                caption=t(label, locale),
                reply_to=notice.message_id,
            )
        except Exception:
            logger.exception("Не удалось отправить медиа правки (%s)", snap["kind"])


@router.callback_query(F.data == "archive:link_unavailable")
async def on_link_unavailable(call: CallbackQuery):
    locale = await db.get_locale(call.from_user.id)
    await call.answer(t("archive.link_unavailable", locale), show_alert=True)


@router.callback_query(F.data == "archive:delete_notice")
async def on_delete_notice(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        log_suppressed("modules/archive.py:delete_notice", benign=True)
    await call.answer()


@router.callback_query(F.data == "archive:delete_pair")
async def on_delete_pair(call: CallbackQuery):
    """Удаляет содержимое и уведомление, на которое оно было ответом."""
    for msg in (call.message, getattr(call.message, "reply_to_message", None)):
        if msg is None:
            continue
        try:
            await msg.delete()
        except Exception:
            log_suppressed("modules/archive.py:delete_pair", benign=True)
    await call.answer()


@router.edited_business_message()
async def on_business_edited(message: Message, bot: Bot):
    connection_id = message.business_connection_id
    disabled = await db.list_disabled_modules(connection_id)
    if "archive" in disabled:
        return

    snap = build_snapshot(message, bot_id=getattr(bot, "id", None))
    if snap is None:
        return

    connection = await db.get_connection(connection_id)
    if not connection:
        return

    is_owner = message.from_user.id == connection["owner_id"]
    old_entry = await db.get_history_entry(
        connection_id, message.chat.id, message.message_id
    )
    old = entry_snapshot(old_entry)
    change = edit_kind(old, snap) if old is not None else None

    if not is_owner and change:
        locale = await db.get_locale(connection["owner_id"])
        mention = format_mention(
            message.from_user.full_name, message.from_user.username, message.chat.id
        )
        try:
            await _notify_edited(
                bot, connection, message, locale, mention, change, old, old_entry, snap
            )
        except Exception:
            log_suppressed("modules/archive.py:notify_edited")

        await db.log_archive_event(
            connection_id,
            message.chat.id,
            message.message_id,
            "edited",
            old["text"],
            snap["text"],
            int(time.time()),
            kind=snap["kind"],
            edit_kind=change,
            old_snapshot=old,
            new_snapshot=snap,
        )

    await db.save_history(
        connection_id,
        message.chat.id,
        message.message_id,
        is_owner,
        snap["text"],
        int(time.time()),
        snapshot=snap,
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
        snap = entry_snapshot(entry)

        mention = format_mention(
            event.chat.full_name, event.chat.username, event.chat.id
        )
        try:
            await _notify_deleted(
                bot, connection["owner_chat_id"], locale, mention, snap, entry
            )
        except Exception:
            log_suppressed("modules/archive.py:notify_deleted")

        await db.log_archive_event(
            connection_id,
            event.chat.id,
            message_id,
            "deleted",
            entry["text"],
            None,
            int(time.time()),
            kind=snap["kind"],
            old_snapshot=snap,
            # байты (если они есть — исчезающие медиа) переезжают в запись архива:
            # историю ниже чистят, а архив должен показывать файл и дальше
            media_type=entry.get("media_type"),
            media_data=entry.get("media_data"),
            media_mime=entry.get("media_mime"),
            media_name=entry.get("media_name"),
            media_status=entry.get("media_status"),
        )
        await db.delete_history(connection_id, event.chat.id, message_id)
