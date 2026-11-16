"""Снимок сообщения (чистая часть: типы, нормализация, сравнение): тип + всё, что нужно, чтобы показать или переотправить его позже.

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
Построение снимка из aiogram-сообщения — `adapter.py`; здесь aiogram нет.
"""

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
PAYLOAD_FIELDS = (
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

KINDS = ("text",) + FILE_KINDS + tuple(k for k, _ in PAYLOAD_FIELDS) + ("other",)

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
    "media_group_id",
    "transcript",
)

# файлы, которые Bot API отдаёт через getFile (лимит 20 МБ)
MAX_DOWNLOAD_BYTES = 20 * 1024 * 1024


def gift_sticker(payload):
    """Стикер подарка из payload (обычный — gift.sticker, уникальный — gift.model.sticker)."""
    gift = (payload or {}).get("gift") or {}
    return gift.get("sticker") or (gift.get("model") or {}).get("sticker") or None


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
        "media_group_id": snap.get("media_group_id"),
        "transcript": snap.get("transcript"),
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


GIFT_KINDS = ("gift", "unique_gift")
