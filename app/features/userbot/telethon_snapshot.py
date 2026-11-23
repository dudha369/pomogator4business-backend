"""Сообщение Telethon -> словарь-снимок (тот же формат, что у `history.adapter.build_snapshot`).

Часть адаптера Telethon: знает имена его классов, но сам библиотеку не импортирует
(работает с атрибутами и именами типов), поэтому тестируется на простых подменах.

`file_id` у юзербота пустой: он привязан к боту. Байты файла юзербот скачивает отдельно
(часть 2), а бот отправляет их заново."""

_ENTITY_TYPES = {
    "MessageEntityBold": "bold",
    "MessageEntityItalic": "italic",
    "MessageEntityUnderline": "underline",
    "MessageEntityStrike": "strikethrough",
    "MessageEntitySpoiler": "spoiler",
    "MessageEntityCode": "code",
    "MessageEntityPre": "pre",
    "MessageEntityUrl": "url",
    "MessageEntityTextUrl": "text_link",
    "MessageEntityMention": "mention",
    "MessageEntityMentionName": "text_mention",
    "MessageEntityHashtag": "hashtag",
    "MessageEntityCashtag": "cashtag",
    "MessageEntityBotCommand": "bot_command",
    "MessageEntityEmail": "email",
    "MessageEntityPhone": "phone_number",
    "MessageEntityBlockquote": "blockquote",
    "MessageEntityCustomEmoji": "custom_emoji",
}


def entities(message) -> list[dict] | None:
    """Сущности в формате Bot API. offset/length у Telegram и так в UTF-16."""
    out = []
    for ent in getattr(message, "entities", None) or []:
        kind = _ENTITY_TYPES.get(type(ent).__name__)
        if kind is None:
            continue
        item = {"type": kind, "offset": ent.offset, "length": ent.length}
        if kind == "blockquote" and getattr(ent, "collapsed", False):
            item["type"] = "expandable_blockquote"
        if kind == "text_link":
            item["url"] = ent.url
        elif kind == "pre":
            item["language"] = getattr(ent, "language", "") or None
        elif kind == "text_mention":
            item["user"] = {"id": ent.user_id}
        elif kind == "custom_emoji":
            item["custom_emoji_id"] = str(ent.document_id)
        out.append({k: v for k, v in item.items() if v is not None})
    return out or None


# (атрибут Message Telethon, kind); порядок важен: у голосового и видеокружка есть document
_FILE_KINDS = (
    ("photo", "photo"),
    ("sticker", "sticker"),
    ("voice", "voice"),
    ("video_note", "video_note"),
    ("gif", "animation"),
    ("video", "video"),
    ("audio", "audio"),
    ("document", "document"),
)
_PAYLOAD_KINDS = ("contact", "poll", "dice")


def _file_payload(message) -> dict | None:
    f = getattr(message, "file", None)
    payload = {
        "duration": getattr(f, "duration", None),
        "width": getattr(f, "width", None),
        "height": getattr(f, "height", None),
        "title": getattr(f, "title", None),
        "performer": getattr(f, "performer", None),
    }
    return {k: v for k, v in payload.items() if v not in (None, "")} or None


def _geo(message) -> dict | None:
    geo = getattr(message, "geo", None)
    if geo is None:
        return None
    return {"latitude": geo.lat, "longitude": geo.long}


def build_snapshot(message) -> dict | None:
    """None — в сообщении нечего хранить (служебное)."""
    text = getattr(message, "message", None) or None
    f = getattr(message, "file", None)
    snap = {
        "kind": None,
        "text": text,
        "entities": entities(message) if text else None,
        "show_caption_above": bool(getattr(message, "invert_media", False)),
        "has_spoiler": False,
        "file_id": None,
        "file_unique_id": None,
        "file_size": getattr(f, "size", None),
        "media_mime": getattr(f, "mime_type", None),
        "media_name": getattr(f, "name", None),
        "payload": None,
        "forward": None,
        "raw_json": None,
        "bot_id": None,
        "media_group_id": (
            str(message.grouped_id) if getattr(message, "grouped_id", None) else None
        ),
    }
    for attr, kind in _FILE_KINDS:
        if getattr(message, attr, None):
            snap.update(kind=kind, payload=_file_payload(message))
            return snap
    if getattr(message, "venue", None):
        snap.update(kind="venue", payload=_geo(message))
        return snap
    if _geo(message):
        snap.update(kind="location", payload=_geo(message))
        return snap
    for kind in _PAYLOAD_KINDS:
        if getattr(message, kind, None):
            snap["kind"] = kind  # подробности (опрос, контакт) — часть 2
            return snap
    if getattr(message, "media", None):
        snap["kind"] = "other"
        return snap
    if text is not None:
        snap["kind"] = "text"
        return snap
    return None


def message_ts(message) -> int:
    return int(message.date.timestamp())
