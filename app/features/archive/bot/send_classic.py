"""Классические (не Rich) уведомления архива: обычные сообщения, подписи к медиа."""

import logging

from aiogram import html
from aiogram.types import (
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    LinkPreviewOptions,
)

from app.features.archive.bot.keyboards import delete_keyboard, sender_keyboard
from app.features.archive.bot.media_io import (
    CAPTIONABLE,
    NO_CAPTION,
    RESENDABLE_DATA,
    file_input,
    send_media,
)
from app.features.archive.render.classic import (
    CAPTION_LIMIT,
    MESSAGE_LIMIT,
    before_after,
    build_notice,
    clip,
    highlight_changes_async,
)
from app.features.archive.service import gift_sticker_id
from app.features.archive.snapshot import GIFT_KINDS
from app.features.history.snapshot import FILE_KINDS
from app.platform.i18n import t

logger = logging.getLogger("bot.archive")
_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
_ALBUM_FAMILY = {
    "photo": "visual",
    "video": "visual",
    "audio": "audio",
    "document": "document",
}
_ALBUM_CLASS = {
    "photo": InputMediaPhoto,
    "video": InputMediaVideo,
    "audio": InputMediaAudio,
    "document": InputMediaDocument,
}


async def _text(bot, chat_id, text, markup):
    return await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode="html",
        reply_markup=markup,
        link_preview_options=_NO_PREVIEW,
    )


# --- удалено --------------------------------------------------------------------


async def deleted(bot, chat_id, locale, mention, sender, snap, entry, header_key, own):
    kind = snap["kind"]
    is_file = kind in FILE_KINDS
    delete_one = delete_keyboard(locale)
    file = file_input(entry, snap) if is_file else None
    send_failed = False

    if kind in CAPTIONABLE and file:
        caption = build_notice(
            locale, mention, snap, limit=CAPTION_LIMIT, header_key=header_key
        )
        try:
            await send_media(
                bot, chat_id, snap, file, caption=caption, markup=delete_one
            )
            return
        except Exception:
            logger.exception("Не удалось отправить сохранённое медиа (%s)", kind)
            send_failed = True

    resend = bool(
        (kind in NO_CAPTION and file)
        or kind in RESENDABLE_DATA
        or (kind in GIFT_KINDS and gift_sticker_id(snap))
    )
    if resend:
        for profile in (True, False):  # профиль может быть закрыт приватностью
            try:
                markup = sender_keyboard(locale, sender, snap, profile=profile, own=own)
                await send_media(bot, chat_id, snap, file, markup=markup)
                return
            except Exception:
                logger.exception(
                    "Не удалось отправить сохранённое содержимое (%s)", kind
                )
        send_failed = True

    text = build_notice(
        locale,
        mention,
        snap,
        limit=MESSAGE_LIMIT - 100,
        header_key=header_key,
        detail=kind != "text" and not is_file,
    )
    if is_file and (not file or send_failed):
        text += "\n\n" + t("archive.media_unavailable", locale)
    await _text(bot, chat_id, text, delete_one)


async def album(bot, chat_id, locale, mention, items, header_key):
    """Альбом без кнопок не отправить: сначала заголовок (с подписью и кнопкой), следом
    сами файлы без подписей. Возвращает [(снимок, запись)], которые в альбом не вошли
    (стикеры, геолокации…) — их показывает вызывающий по одному."""
    snaps = [snap for snap, _ in items]
    forward = next((s["forward"] for s in snaps if s.get("forward")), None)
    caption_snap = next((s for s in snaps if s.get("text")), {})
    header = build_notice(
        locale,
        mention,
        {**caption_snap, "forward": forward},
        limit=MESSAGE_LIMIT - 100,
        header_key=header_key,
    )
    await _text(bot, chat_id, header, delete_keyboard(locale))

    families = {"visual": [], "audio": [], "document": []}
    leftovers = []
    for snap, entry in items:
        file = file_input(entry, snap)
        family = _ALBUM_FAMILY.get(snap["kind"])
        if file and family:
            families[family].append((snap, file))
        else:
            leftovers.append((snap, entry))
    for members in families.values():
        for start in range(0, len(members), 10):  # в альбоме не больше 10 файлов
            chunk = members[start : start + 10]
            media = [_ALBUM_CLASS[snap["kind"]](media=file) for snap, file in chunk]
            await bot.send_media_group(chat_id=chat_id, media=media)
    return leftovers


# --- изменено -------------------------------------------------------------------


async def edited_text(bot, chat_id, locale, mention, old, new, link_kb):
    text = t(
        "archive.edited_notice",
        locale,
        mention=mention,
        # обрезаем: без этого два текста по 4096 дают >4096 и Telegram отклоняет
        old_text=html.quote(clip(old["text"])),
        new_text=await highlight_changes_async(clip(old["text"]), clip(new["text"])),
    )
    return (await _text(bot, chat_id, text, link_kb)).message_id


async def edited_caption(bot, chat_id, locale, mention, old, new, link_kb):
    header = t("archive.edited_caption_header", locale, mention=mention)
    text = header + await before_after(locale, old["text"], new["text"])
    return (await _text(bot, chat_id, text, link_kb)).message_id


async def edited_media(
    bot, chat_id, locale, mention, change, old, old_entry, new, link_kb
):
    """Замена файла: сообщение «изменено» и под ним файлы «Было»/«Стало»."""
    text = t("archive.edited_media_header", locale, mention=mention)
    if change == "media_caption":
        text += await before_after(locale, old["text"], new["text"])
    notice = await _text(bot, chat_id, text, link_kb)
    for snap, entry, label in (
        (old, old_entry, "archive.caption_before"),
        (new, None, "archive.caption_after"),
    ):
        file = file_input(entry, snap)
        if not file:
            continue
        try:
            await send_media(
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
