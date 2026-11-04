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
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
    Message,
    ReplyParameters,
)

from config import settings
from core import database as db
from core.archive_notice import (
    CAPTION_LIMIT,
    EMPTY,
    MESSAGE_LIMIT,
    build_notice,
    forward_link,
    user_link,
)
from core.archive_rich import (
    VISUAL,
    build_deleted,
    build_edited_media,
    can_use_rich,
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


_ICON_DELETED = "5258130763148172425"
_ICON_USER = "5260399854500191689"
_ICON_FORWARD = "5260450573768990626"


def _sender_keyboard(locale, sender, snap, *, profile=True):
    rows = [
        [
            InlineKeyboardButton(
                text=t("archive.btn_deleted", locale),
                icon_custom_emoji_id=_ICON_DELETED,
                callback_data="archive:info",
            )
        ]
    ]
    link = user_link(sender.get("id"), sender.get("username"))
    if profile and link:
        rows.append(
            [
                InlineKeyboardButton(
                    text=sender.get("name") or "—",
                    icon_custom_emoji_id=_ICON_USER,
                    url=link,
                )
            ]
        )
    forward = snap.get("forward")
    if forward:
        label = t(
            "archive.btn_forwarded",
            locale,
            name=forward.get("name") or forward.get("signature") or "—",
        )
        href = forward_link(forward)
        rows.append(
            [
                InlineKeyboardButton(
                    text=label, icon_custom_emoji_id=_ICON_FORWARD, url=href
                )
                if href
                else InlineKeyboardButton(
                    text=label,
                    icon_custom_emoji_id=_ICON_FORWARD,
                    callback_data="archive:info",
                )
            ]
        )
    rows.append(_delete_button_keyboard(locale).inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _try_rich(bot, chat_id, rich_message, markup):
    """Отправляет Rich Message; False — не получилось (шлём обычным способом)."""
    try:
        await bot.send_rich_message(
            chat_id=chat_id, rich_message=rich_message, reply_markup=markup
        )
        return True
    except Exception:
        logger.warning(
            "Rich-уведомление не отправилось, используем обычное", exc_info=True
        )
        return False


async def _notify_deleted(bot, chat_id, locale, mention, sender, snap, entry):
    kind = snap["kind"]
    is_file = kind in FILE_KINDS
    delete_one = _delete_button_keyboard(locale)

    if settings.ARCHIVE_RICH and can_use_rich([(snap, entry)]):
        rich = build_deleted(locale, mention, [snap], snap.get("forward"))
        if await _try_rich(bot, chat_id, rich, delete_one):
            return

    file = _file_input(entry, snap) if is_file else None
    send_failed = False

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

    if (kind in _NO_CAPTION and file) or kind in _RESENDABLE_DATA:
        for profile in (
            True,
            False,
        ):
            try:
                await _send_media(
                    bot,
                    chat_id,
                    snap,
                    file,
                    markup=_sender_keyboard(locale, sender, snap, profile=profile),
                )
                return
            except Exception:
                logger.exception(
                    "Не удалось отправить сохранённое содержимое (%s)", kind
                )
        send_failed = True

    detail = kind != "text" and not is_file and kind not in _RESENDABLE_DATA
    text = build_notice(locale, mention, snap, limit=MESSAGE_LIMIT - 100, detail=detail)
    if is_file and (not file or send_failed):
        text += "\n\n" + t("archive.media_unavailable", locale)
    elif kind in _RESENDABLE_DATA and send_failed:
        text += "\n\n" + build_notice(locale, mention, snap, limit=300, detail=True)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=delete_one,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def _notify_album(bot, chat_id, locale, mention, sender, items):
    snaps = [snap for snap, _ in items]
    forward = next((s["forward"] for s in snaps if s.get("forward")), None)
    delete_one = _delete_button_keyboard(locale)

    if settings.ARCHIVE_RICH and can_use_rich(items):
        rich = build_deleted(locale, mention, snaps, forward)
        if await _try_rich(bot, chat_id, rich, delete_one):
            return

    caption_snap = next((s for s in snaps if s.get("text")), {})
    header = build_notice(
        locale,
        mention,
        {**caption_snap, "forward": forward},
        limit=CAPTION_LIMIT,
    )
    families = {"visual": [], "audio": [], "document": []}
    leftovers = []
    for snap, entry in items:
        file = _file_input(entry, snap)
        family = {
            "photo": "visual",
            "video": "visual",
            "audio": "audio",
            "document": "document",
        }.get(snap["kind"])
        if file and family:
            families[family].append((snap, file))
        else:
            leftovers.append((snap, entry))

    first = True
    for family, members in families.items():
        for start in range(0, len(members), 10):
            chunk = members[start : start + 10]
            media = []
            for index, (snap, file) in enumerate(chunk):
                kwargs = {"media": file}
                if first and index == 0:
                    kwargs["caption"] = header
                    if family == "visual":
                        kwargs["show_caption_above_media"] = True
                cls = {
                    "photo": InputMediaPhoto,
                    "video": InputMediaVideo,
                    "audio": InputMediaAudio,
                    "document": InputMediaDocument,
                }[snap["kind"]]
                media.append(cls(**kwargs))
            await bot.send_media_group(chat_id=chat_id, media=media)
            first = False
    for snap, entry in leftovers:
        await _notify_deleted(bot, chat_id, locale, mention, sender, snap, entry)
    if not first:  # альбом ушёл без кнопок — даём одну для всего уведомления
        await bot.send_message(
            chat_id=chat_id,
            text=t("archive.btn_deleted", locale),
            reply_markup=delete_one,
        )


def _clip(text):
    text = text or ""
    return text if len(text) <= _CLIP else text[:_CLIP].rstrip() + "…"


def _before_after(locale, old_text, new_text):
    old_html = escape(_clip(old_text)) or EMPTY
    new_html = (
        highlight_changes(_clip(old_text), _clip(new_text)) if new_text else EMPTY
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

    if (
        settings.ARCHIVE_RICH
        and old["kind"] in VISUAL
        and new["kind"] in VISUAL
        and can_use_rich([(old, old_entry), (new, None)])
    ):
        rich = build_edited_media(
            locale,
            mention,
            old,
            new,
            caption_changed=change == "media_caption",
            old_text=old["text"],
            new_text=new["text"],
        )
        if await _try_rich(bot, chat_id, rich, link_kb):
            return

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


@router.callback_query(F.data == "archive:info")
async def on_info(call: CallbackQuery):
    locale = await db.get_locale(call.from_user.id)
    await call.answer(t("archive.toast_deleted", locale))


def _group_albums(items):
    units, by_group = [], {}
    for item in items:
        group_id = item[2].get("media_group_id")
        if not group_id:
            units.append([item])
        elif group_id in by_group:
            by_group[group_id].append(item)
        else:
            by_group[group_id] = [item]
            units.append(by_group[group_id])
    for unit in units:
        unit.sort(key=lambda item: item[0])
    return units


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
    mention = format_mention(event.chat.full_name, event.chat.username, event.chat.id)
    sender = {
        "id": event.chat.id,
        "username": getattr(event.chat, "username", None),
        "name": event.chat.full_name,
    }

    found = []
    for message_id in event.message_ids:
        if consume_self_delete(connection_id, event.chat.id, message_id):
            await db.delete_history(connection_id, event.chat.id, message_id)
            continue
        entry = await db.get_history_entry(connection_id, event.chat.id, message_id)
        if entry is not None:
            found.append((message_id, entry, entry_snapshot(entry)))

    for unit in _group_albums(found):
        try:
            if len(unit) == 1:
                _, entry, snap = unit[0]
                await _notify_deleted(
                    bot,
                    connection["owner_chat_id"],
                    locale,
                    mention,
                    sender,
                    snap,
                    entry,
                )
            else:
                await _notify_album(
                    bot,
                    connection["owner_chat_id"],
                    locale,
                    mention,
                    sender,
                    [(snap, entry) for _, entry, snap in unit],
                )
        except Exception:
            log_suppressed("modules/archive.py:notify_deleted")

        for message_id, entry, snap in unit:
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
                media_type=entry.get("media_type"),
                media_data=entry.get("media_data"),
                media_mime=entry.get("media_mime"),
                media_name=entry.get("media_name"),
                media_status=entry.get("media_status"),
            )
            await db.delete_history(connection_id, event.chat.id, message_id)
