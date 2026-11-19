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

KINDS = ("text", *FILE_KINDS, *(k for k, _ in PAYLOAD_FIELDS), "other")

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
