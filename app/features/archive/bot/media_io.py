"""Как переслать сохранённое содержимое: файл (байты или file_id), геолокация, контакт."""

from aiogram.types import BufferedInputFile, ReplyParameters

from app.features.archive.service import gift_sticker_id
from app.features.archive.snapshot import GIFT_KINDS

CAPTIONABLE = {
    "photo": ("send_photo", "photo"),
    "video": ("send_video", "video"),
    "animation": ("send_animation", "animation"),
    "voice": ("send_voice", "voice"),
    "audio": ("send_audio", "audio"),
    "document": ("send_document", "document"),
}
CAPTION_ABOVE = {"photo", "video", "animation"}
NO_CAPTION = {
    "sticker": ("send_sticker", "sticker"),
    "video_note": ("send_video_note", "video_note"),
}
RESENDABLE_DATA = {"location", "venue", "contact"}


def file_input(entry, snap):
    """Что передать в send_*: байты (если мы их сохраняли) или file_id."""
    data = (entry or {}).get("media_data")
    if data:
        return BufferedInputFile(
            bytes(data), filename=snap.get("media_name") or f"deleted_{snap['kind']}"
        )
    return snap.get("file_id")


async def send_media(
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

    if kind in CAPTIONABLE:
        method, arg = CAPTIONABLE[kind]
        if caption:
            extra["caption"] = caption
            extra["parse_mode"] = "html"  # подпись собрана как HTML (tg-emoji, <b>)
            if kind in CAPTION_ABOVE and above:
                extra["show_caption_above_media"] = True
        if kind in CAPTION_ABOVE and snap.get("has_spoiler"):
            extra["has_spoiler"] = True
        return await getattr(bot, method)(chat_id=chat_id, **{arg: file}, **extra)
    if kind in NO_CAPTION:
        method, arg = NO_CAPTION[kind]
        return await getattr(bot, method)(chat_id=chat_id, **{arg: file}, **extra)
    if kind in GIFT_KINDS:
        return await bot.send_sticker(
            chat_id=chat_id, sticker=gift_sticker_id(snap), **extra
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
