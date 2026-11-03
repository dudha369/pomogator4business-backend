"""Снимок сообщения: тип + всё, что нужно, чтобы показать или переотправить его позже.

Вместо байтов храним идентификаторы Telegram (file_id) и описание содержимого.
Любое сообщение раскладывается так:

- ``kind``        — тип (см. KINDS);
- ``text``        — текст или подпись; ``entities`` — их форматирование (в т.ч. премиум-эмодзи);
- ``file_*``      — файл, если он есть (file_id, file_unique_id, размер, mime, имя);
- ``payload``     — всё специфичное для типа (геолокация, контакт, опрос, подарок, длительность…);
- ``forward``     — от кого переслано (если переслано);
- ``raw_json``    — полный JSON сообщения: новые и экзотические типы не теряются,
                    даже пока для них нет красивого отображения.

Снимок — обычный словарь, ключи совпадают с колонками таблицы message_history.
"""

from core.media import describe_media

FILE_KINDS = (
    "photo",
    "video",
    "video_note",
    "voice",
    "animation",
    "audio",
    "sticker",
    "document",
)

# тип -> имя поля Message; порядок важен (у venue есть и location)
_PAYLOAD_FIELDS = (
    ("venue", "venue"),
    ("location", "location"),
    ("contact", "contact"),
    ("poll", "poll"),
    ("dice", "dice"),
    ("gift", "gift"),
    ("unique_gift", "unique_gift"),
    ("story", "story"),
    ("checklist", "checklist"),
    ("paid_media", "paid_media"),
    ("live_photo", "live_photo"),
)

KINDS = ("text",) + FILE_KINDS + tuple(k for k, _ in _PAYLOAD_FIELDS) + ("other",)

# колонки message_history, которые заполняет снимок
SNAPSHOT_COLUMNS = (
    "kind",
    "entities",
    "show_caption_above",
    "has_spoiler",
    "file_id",
    "file_unique_id",
    "file_size",
    "payload",
    "forward",
    "raw_json",
    "bot_id",
)

# файлы, которые Bot API отдаёт через getFile (лимит 20 МБ)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def _dump(obj):
    """Объект Telegram -> словарь без пустых полей (JSON-совместимый)."""
    if obj is None:
        return None
    if hasattr(obj, "model_dump"):
        return obj.model_dump(mode="json", exclude_none=True)
    if hasattr(obj, "__dict__"):
        return {
            k: v
            for k, v in vars(obj).items()
            if not k.startswith("_") and isinstance(v, (str, int, float, bool))
        }
    return None


def _entities(message):
    raw = getattr(message, "entities", None) or getattr(
        message, "caption_entities", None
    )
    if not raw:
        return None
    out = [_dump(e) for e in raw]
    return [e for e in out if e] or None


def _forward(message):
    origin = getattr(message, "forward_origin", None)
    if origin is None:
        return None
    kind = getattr(origin, "type", None)
    if kind == "user":
        user = origin.sender_user
        return {
            "type": "user",
            "id": user.id,
            "name": user.full_name,
            "username": getattr(user, "username", None),
        }
    if kind == "hidden_user":
        return {"type": "hidden_user", "name": origin.sender_user_name}
    if kind in ("chat", "channel"):
        chat = origin.sender_chat if kind == "chat" else origin.chat
        return {
            "type": kind,
            "id": chat.id,
            "name": getattr(chat, "title", None),
            "username": getattr(chat, "username", None),
            "message_id": getattr(origin, "message_id", None),
            "signature": getattr(origin, "author_signature", None),
        }
    return {"type": str(kind), "name": None}


def _file_payload(kind, obj):
    thumb = getattr(obj, "thumbnail", None) or getattr(obj, "thumb", None)
    payload = {
        "duration": getattr(obj, "duration", None),
        "width": getattr(obj, "width", None),
        "height": getattr(obj, "height", None),
        "thumbnail_file_id": getattr(thumb, "file_id", None),
    }
    if kind == "photo":
        payload["duration"] = None
    if kind == "video_note":
        payload["width"] = payload["height"] = getattr(obj, "length", None)
    if kind == "sticker":
        payload.update(
            emoji=getattr(obj, "emoji", None),
            set_name=getattr(obj, "set_name", None),
            is_animated=bool(getattr(obj, "is_animated", False)),
            is_video=bool(getattr(obj, "is_video", False)),
            custom_emoji_id=getattr(obj, "custom_emoji_id", None),
        )
    if kind == "audio":
        payload.update(
            title=getattr(obj, "title", None),
            performer=getattr(obj, "performer", None),
        )
    return {k: v for k, v in payload.items() if v not in (None, "")} or None


def _raw(message):
    if not hasattr(message, "model_dump"):
        return None
    try:
        return message.model_dump(
            mode="json",
            exclude_none=True,
            exclude={"reply_to_message", "external_reply"},
        )
    except Exception:
        return None


def build_snapshot(message, bot_id=None):
    """Message -> снимок (dict) или None, если в сообщении нечего хранить."""
    text = getattr(message, "text", None) or getattr(message, "caption", None)
    snap = {
        "kind": None,
        "text": text,
        "entities": _entities(message) if text else None,
        "show_caption_above": bool(getattr(message, "show_caption_above_media", None)),
        "has_spoiler": bool(getattr(message, "has_media_spoiler", None)),
        "file_id": None,
        "file_unique_id": None,
        "file_size": None,
        "media_mime": None,
        "media_name": None,
        "payload": None,
        "forward": _forward(message),
        "raw_json": _raw(message),
        "bot_id": bot_id,
    }

    described = describe_media(message)
    if described is not None:
        kind, obj, mime, name = described
        snap.update(
            kind=kind,
            file_id=getattr(obj, "file_id", None),
            file_unique_id=getattr(obj, "file_unique_id", None),
            file_size=getattr(obj, "file_size", None),
            media_mime=mime,
            media_name=name,
            payload=_file_payload(kind, obj),
        )
        return snap

    for kind, attr in _PAYLOAD_FIELDS:
        value = getattr(message, attr, None)
        if value:
            snap.update(kind=kind, payload=_dump(value))
            return snap

    if text is not None:
        snap["kind"] = "text"
        return snap
    return None


def entry_snapshot(entry):
    """Строка message_history (в т.ч. старая, до появления снимков) -> снимок."""
    if entry is None:
        return None
    snap = {c: entry.get(c) for c in SNAPSHOT_COLUMNS}
    snap["text"] = entry.get("text")
    snap["media_mime"] = entry.get("media_mime")
    snap["media_name"] = entry.get("media_name")
    snap["show_caption_above"] = bool(snap["show_caption_above"])
    snap["has_spoiler"] = bool(snap["has_spoiler"])
    if not snap["kind"]:  # запись создана до миграции
        snap["kind"] = entry.get("media_type") or "text"
    return snap


def public_view(snap):
    """Что отдаём веб-интерфейсу: без raw_json и без file_id (файл — через /media)."""
    if not snap:
        return None
    size = snap.get("file_size")
    return {
        "kind": snap.get("kind"),
        "text": snap.get("text"),
        "entities": snap.get("entities"),
        "show_caption_above": bool(snap.get("show_caption_above")),
        "has_spoiler": bool(snap.get("has_spoiler")),
        "has_file": bool(snap.get("file_id")),
        "file_size": size,
        "too_large": bool(size and size > MAX_DOWNLOAD_BYTES),
        "mime": snap.get("media_mime"),
        "file_name": snap.get("media_name"),
        "payload": snap.get("payload"),
        "forward": snap.get("forward"),
    }


def edit_kind(old, new):
    """Что именно изменилось при правке: text | caption | caption_removed | media |
    media_caption или None, если ничего заметного."""
    old_text, new_text = old.get("text") or "", new.get("text") or ""
    text_changed = old_text != new_text
    has_file = new.get("kind") in FILE_KINDS
    if not has_file:
        return "text" if text_changed else None

    old_uid, new_uid = old.get("file_unique_id"), new.get("file_unique_id")
    media_changed = bool(old_uid and new_uid and old_uid != new_uid)
    if media_changed and text_changed:
        return "media_caption"
    if media_changed:
        return "media"
    if text_changed:
        return "caption_removed" if not new_text else "caption"
    return None
