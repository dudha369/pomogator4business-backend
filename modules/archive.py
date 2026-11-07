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
    build_deleted,
    build_edit_history,
    build_edited_media,
    build_location,
    can_use_rich,
)
from core.archive_prefs import defaults, load_prefs
from core.i18n import t
from core.mentions import format_mention
from core.registry import registry
from core.self_actions import consume_self_delete
from core.snapshot import (
    FILE_KINDS,
    build_snapshot,
    edit_kind,
    entry_snapshot,
    gift_sticker,
)
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
_GIFT_KINDS = {"gift", "unique_gift"}
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
                    icon_custom_emoji_id=_ICON_TRASH,
                    style="danger",
                    callback_data=callback,
                )
            ]
        ]
    )


def _gift_sticker(snap):
    """file_id стикера подарка."""
    return snap.get("file_id") or (gift_sticker(snap.get("payload")) or {}).get(
        "file_id"
    )


def _gift_summary(snap):
    """Коротко о подарке — для текста на кнопке."""
    payload = snap.get("payload") or {}
    gift = payload.get("gift") or {}
    if snap.get("kind") == "unique_gift":
        return f"{gift.get('base_name') or gift.get('name') or ''} #{gift.get('number') or ''}".strip()
    parts = []
    if gift.get("star_count"):
        parts.append(f"⭐ {gift['star_count']}")
    if payload.get("text"):
        parts.append(payload["text"][:40])
    return " · ".join(parts)


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
    if kind in _GIFT_KINDS:
        return await bot.send_sticker(
            chat_id=chat_id, sticker=_gift_sticker(snap), **extra
        )
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


_ICON_DELETED = "5258389041006518073"  # коробка: «сообщение в архиве»
_ICON_TRASH = "5258130763148172425"  # мусорка — только для «Удалить у себя»
_ICON_GIFT = "5963213811597970978"
_ICON_USER = "5260399854500191689"
_ICON_FORWARD = "5260450573768990626"


def _sender_keyboard(locale, sender, snap, *, profile=True):
    """Кнопки под содержимым, к которому нельзя дописать подпись (стикер, кружок,
    геолокация, контакт, подарок). Сверху серая «заглушка» со статусом, ниже цветные
    рабочие кнопки: профиль и «переслано от» (синие), «Удалить у себя» (красная)."""
    rows = [
        [
            InlineKeyboardButton(
                text=t("archive.btn_deleted", locale),
                icon_custom_emoji_id=_ICON_DELETED,
                callback_data="archive:info",
            )
        ]
    ]
    if snap.get("kind") in _GIFT_KINDS and _gift_summary(snap):
        rows.append(
            [
                InlineKeyboardButton(
                    text=_gift_summary(snap),
                    icon_custom_emoji_id=_ICON_GIFT,
                    callback_data="archive:info",
                )
            ]
        )
    link = user_link(sender.get("id"), sender.get("username"))
    if profile and link:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(
                        "archive.btn_sender", locale, name=sender.get("name") or "—"
                    ),
                    icon_custom_emoji_id=_ICON_USER,
                    style="primary",
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
                (
                    InlineKeyboardButton(
                        text=label,
                        icon_custom_emoji_id=_ICON_FORWARD,
                        style="primary",
                        url=href,
                    )
                    if href
                    else InlineKeyboardButton(
                        text=label,
                        icon_custom_emoji_id=_ICON_FORWARD,
                        callback_data="archive:info",
                    )
                )
            ]
        )
    rows.append(_delete_button_keyboard(locale).inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_rich(bot, chat_id, rich_message, markup):
    """Отправляет Rich Message; возвращает message_id или None (шлём обычным способом)."""
    try:
        sent = await bot.send_rich_message(
            chat_id=chat_id, rich_message=rich_message, reply_markup=markup
        )
        return sent.message_id
    except Exception:
        logger.warning(
            "Rich-уведомление не отправилось, используем обычное", exc_info=True
        )
        return None


async def _try_rich(bot, chat_id, rich_message, markup):
    return await _send_rich(bot, chat_id, rich_message, markup) is not None


async def _notify_deleted(bot, chat_id, locale, mention, sender, snap, entry, prefs):
    kind = snap["kind"]
    is_file = kind in FILE_KINDS
    delete_one = _delete_button_keyboard(locale)

    if can_use_rich([(snap, entry)], prefs):
        rich = build_deleted(locale, mention, [snap], snap.get("forward"), prefs)
        if await _try_rich(bot, chat_id, rich, delete_one):
            return
    if prefs.rich and prefs.location_map and kind in ("location", "venue"):
        rich = build_location(locale, mention, snap, snap.get("forward"), prefs)
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

    resend = bool(
        (kind in _NO_CAPTION and file)
        or kind in _RESENDABLE_DATA
        or (kind in _GIFT_KINDS and _gift_sticker(snap))
    )
    if resend:
        for profile in (True, False):  # профиль может быть закрыт приватностью
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

    detail = kind != "text" and not is_file
    text = build_notice(locale, mention, snap, limit=MESSAGE_LIMIT - 100, detail=detail)
    if is_file and (not file or send_failed):
        text += "\n\n" + t("archive.media_unavailable", locale)
    await bot.send_message(
        chat_id=chat_id,
        text=text,
        reply_markup=delete_one,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def _notify_album(bot, chat_id, locale, mention, sender, items, prefs):
    """Весь удалённый альбом одним уведомлением (items — [(снимок, запись)])."""
    snaps = [snap for snap, _ in items]
    forward = next((s["forward"] for s in snaps if s.get("forward")), None)
    delete_one = _delete_button_keyboard(locale)

    if can_use_rich(items, prefs):
        rich = build_deleted(locale, mention, snaps, forward, prefs)
        if await _try_rich(bot, chat_id, rich, delete_one):
            return

    # обычный способ: альбом без кнопок не отправить, поэтому сначала заголовок
    # (с подписью и кнопкой), а следом сами альбомы без подписей
    caption_snap = next((s for s in snaps if s.get("text")), {})
    header = build_notice(
        locale,
        mention,
        {**caption_snap, "forward": forward},
        limit=MESSAGE_LIMIT - 100,
    )
    await bot.send_message(
        chat_id=chat_id,
        text=header,
        reply_markup=delete_one,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
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

    classes = {
        "photo": InputMediaPhoto,
        "video": InputMediaVideo,
        "audio": InputMediaAudio,
        "document": InputMediaDocument,
    }
    for members in families.values():
        for start in range(0, len(members), 10):  # в альбоме не больше 10 файлов
            chunk = members[start : start + 10]
            media = [classes[snap["kind"]](media=file) for snap, file in chunk]
            await bot.send_media_group(chat_id=chat_id, media=media)
    for snap, entry in leftovers:
        await _notify_deleted(bot, chat_id, locale, mention, sender, snap, entry, prefs)


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


_TEXT_EDITS = ("text", "caption", "caption_removed", "media_caption")


def _versions(previous, old, new, now, created_at=None):
    """Цепочка версий текста [первая … текущая] и время каждой.

    previous — прошлые правки этого сообщения из архива. Если цепочка не сходится
    (например, часть правок пропущена), начинаем с последней известной версии."""
    rows = [r for r in previous if r["edit_kind"] in _TEXT_EDITS]
    versions = [rows[0]["old_text"] or ""] if rows else [old["text"] or ""]
    times = [created_at]
    for row in rows:
        versions.append(row["new_text"] or "")
        times.append(row["created_at"])
    if versions[-1] != (old["text"] or ""):
        versions, times = [old["text"] or ""], [None]
    versions.append(new["text"] or "")
    times.append(now)
    return versions, times


def _history_media(new, message_id, album_entries, prefs):
    """Что показать над «Было/Стало» у правки подписи: файл (или весь альбом)."""
    if not prefs.caption_edit_media or new.get("kind") not in FILE_KINDS:
        return []
    items = [
        (new, None) if e["message_id"] == message_id else (entry_snapshot(e), e)
        for e in album_entries
    ]
    if not any(snap is new for snap, _ in items):
        items.append((new, None))
    if can_use_rich(items, prefs):
        return [snap for snap, _ in items]
    return [new] if can_use_rich([(new, None)], prefs) else []


async def _notify_edit_history(
    bot,
    connection,
    message,
    locale,
    mention,
    change,
    old,
    new,
    previous,
    link_kb,
    created_at,
    prefs,
):
    """Правка текста/подписи: ОДНО сообщение на всё сообщение собеседника.

    Первое уведомление отправляем, на каждую следующую правку тем же сообщением
    обновляем историю (ранние версии сворачиваются). Возвращает id уведомления."""
    chat_id = connection["owner_chat_id"]
    now = int(time.time())
    if not prefs.edit_history:
        previous = []  # каждая правка — отдельное уведомление
    versions, times = _versions(previous, old, new, now, created_at)

    albums = []
    if new.get("media_group_id"):
        albums = await db.list_album(
            connection["connection_id"], message.chat.id, new["media_group_id"]
        )
    media = _history_media(new, message.message_id, albums, prefs)
    header_key = (
        "archive.edited_text_header"
        if change == "text"
        else "archive.edited_caption_header"
    )
    rich = build_edit_history(
        locale,
        mention,
        versions,
        times,
        current_html=highlight_changes(_clip(versions[-2]), _clip(versions[-1]))
        or EMPTY,
        header_key=header_key,
        media_snaps=media,
        prefs=prefs,
    )

    notice_id = next(
        (
            r["notice_message_id"]
            for r in reversed(previous)
            if r["notice_message_id"] and r["edit_kind"] in _TEXT_EDITS
        ),
        None,
    )
    if notice_id:
        try:
            await bot.edit_message_text(
                chat_id=chat_id,
                message_id=notice_id,
                rich_message=rich,
                reply_markup=link_kb,
            )
            return notice_id
        except Exception:
            # уведомление удалили у себя или оно устарело — начинаем новое
            logger.info("Не удалось обновить уведомление %s", notice_id, exc_info=True)
    return await _send_rich(bot, chat_id, rich, link_kb)


async def _notify_edited(
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
    link_kb = _link_keyboard(
        locale, getattr(message.chat, "username", None), message.message_id
    )
    no_preview = LinkPreviewOptions(is_disabled=True)

    if prefs.rich and change in _TEXT_EDITS[:3]:
        notice_id = await _notify_edit_history(
            bot,
            connection,
            message,
            locale,
            mention,
            change,
            old,
            new,
            previous,
            link_kb,
            (old_entry or {}).get("created_at"),
            prefs,
        )
        if notice_id:
            return notice_id

    if change == "text":
        text = t(
            "archive.edited_notice",
            locale,
            mention=mention,
            old_text=html.quote(old["text"] or ""),
            new_text=highlight_changes(old["text"] or "", new["text"] or ""),
        )
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=link_kb,
            link_preview_options=no_preview,
        )
        return sent.message_id

    if change in ("caption", "caption_removed"):
        header = t("archive.edited_caption_header", locale, mention=mention)
        text = header + _before_after(locale, old["text"], new["text"])
        sent = await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=link_kb,
            link_preview_options=no_preview,
        )
        return sent.message_id

    # media / media_caption: «было» и «стало» одним Rich, если файлы подходят
    if (
        prefs.rich
        and old["kind"] in FILE_KINDS
        and new["kind"] in FILE_KINDS
        and can_use_rich([(old, old_entry), (new, None)], prefs)
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
        notice_id = await _send_rich(bot, chat_id, rich, link_kb)
        if notice_id:
            return notice_id

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
    return notice.message_id


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
        previous = await db.get_edit_history(
            connection_id, message.chat.id, message.message_id
        )
        notice_id = None
        try:
            notice_id = await _notify_edited(
                bot,
                connection,
                message,
                locale,
                mention,
                change,
                old,
                old_entry,
                snap,
                previous,
                await load_prefs(connection_id),
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
            notice_message_id=notice_id,
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
    prefs = await load_prefs(connection_id)
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
                    prefs,
                )
            else:
                await _notify_album(
                    bot,
                    connection["owner_chat_id"],
                    locale,
                    mention,
                    sender,
                    [(snap, entry) for _, entry, snap in unit],
                    prefs,
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
