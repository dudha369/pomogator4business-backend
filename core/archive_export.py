"""Экспорт архива удалённых/изменённых сообщений в HTML, CSV или JSON.

Всё построение — чистые функции от уже собранных данных (записи, имена
чатов, байты фото), без обращений к БД и Telegram: так их проще тестировать.
Сбор данных и отправка файла — в api/archive_export.py."""

import base64
import csv
import datetime
import html
import io
import json

LABELS = {
    "ru": {
        "title": "Архив сообщений",
        "exported": "Выгружено",
        "deleted": "Удалено",
        "edited": "Изменено",
        "was": "Было",
        "became": "Стало",
        "media_omitted": "медиа не включено",
        "media": {
            "photo": "фото",
            "video": "видео",
            "voice": "голосовое",
            "video_note": "кружок",
        },
        "total": "Записей",
        "unknown": "Чат",
    },
    "en": {
        "title": "Message archive",
        "exported": "Exported",
        "deleted": "Deleted",
        "edited": "Edited",
        "was": "Was",
        "became": "Now",
        "media_omitted": "media not included",
        "media": {
            "photo": "photo",
            "video": "video",
            "voice": "voice message",
            "video_note": "video note",
        },
        "total": "Entries",
        "unknown": "Chat",
    },
    "uk": {
        "title": "Архів повідомлень",
        "exported": "Вивантажено",
        "deleted": "Видалено",
        "edited": "Змінено",
        "was": "Було",
        "became": "Стало",
        "media_omitted": "медіа не включено",
        "media": {
            "photo": "фото",
            "video": "відео",
            "voice": "голосове",
            "video_note": "кружок",
        },
        "total": "Записів",
        "unknown": "Чат",
    },
}

_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def labels(locale: str) -> dict:
    return LABELS.get(locale, LABELS["ru"])


def format_ts(ts: int, offset_minutes: int) -> str:
    """Время в часовом поясе владельца: 2026-10-10 14:03:22."""
    moment = datetime.datetime.fromtimestamp(
        ts + offset_minutes * 60, datetime.timezone.utc
    )
    return moment.strftime("%Y-%m-%d %H:%M:%S")


def chat_label(chat_names: dict, chat_id: int, locale: str) -> str:
    return chat_names.get(chat_id) or f"{labels(locale)['unknown']} {chat_id}"


def order_entries(entries, group_by_chat: bool):
    """По времени от старых к новым; при группировке — сначала по чатам (чаты
    идут в порядке их самого раннего события)."""
    if not group_by_chat:
        return sorted(entries, key=lambda e: (e["created_at"], e["log_id"]))
    first_seen = {}
    for e in sorted(entries, key=lambda e: (e["created_at"], e["log_id"])):
        first_seen.setdefault(e["chat_id"], e["created_at"])
    return sorted(
        entries,
        key=lambda e: (
            first_seen[e["chat_id"]],
            e["chat_id"],
            e["created_at"],
            e["log_id"],
        ),
    )


# ------------------------------- JSON / CSV ---------------------------------


def build_json(
    entries, chat_names, offset_minutes, locale, now_ts, group_by_chat=True
) -> bytes:
    rows = []
    for e in order_entries(entries, group_by_chat):
        rows.append(
            {
                "log_id": e["log_id"],
                "chat_id": e["chat_id"],
                "chat_name": chat_names.get(e["chat_id"]),
                "message_id": e["message_id"],
                "event": e["event"],
                "old_text": e["old_text"],
                "new_text": e["new_text"],
                "media_type": e.get("media_type"),
                "created_at": e["created_at"],
                "created_at_local": format_ts(e["created_at"], offset_minutes),
            }
        )
    payload = {
        "exported_at": format_ts(now_ts, offset_minutes),
        "timezone_offset_minutes": offset_minutes,
        "count": len(rows),
        "entries": rows,
    }
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def _csv_safe(value) -> str:
    """Защита от CSV-инъекций: Excel исполняет ячейки, начинающиеся с = + - @."""
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(_CSV_FORMULA_PREFIXES) else text


def build_csv(entries, chat_names, offset_minutes, locale, group_by_chat=True) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        ["date", "chat_id", "chat_name", "event", "old_text", "new_text", "media_type"]
    )
    for e in order_entries(entries, group_by_chat):
        writer.writerow(
            [
                format_ts(e["created_at"], offset_minutes),
                e["chat_id"],
                _csv_safe(chat_names.get(e["chat_id"])),
                e["event"],
                _csv_safe(e["old_text"]),
                _csv_safe(e["new_text"]),
                e.get("media_type") or "",
            ]
        )
    # utf-8-sig — чтобы Excel сам распознал кодировку (иначе кириллица «поплывёт»)
    return buffer.getvalue().encode("utf-8-sig")


# --------------------------------- HTML -------------------------------------

_CSS = """
:root{color-scheme:light dark;--bg:#fff;--card:#f4f5f7;--fg:#111;--hint:#6b7280;--line:#e5e7eb;--del:#dc2626;--edit:#d97706}
@media(prefers-color-scheme:dark){:root{--bg:#111318;--card:#1b1e26;--fg:#f3f4f6;--hint:#9ca3af;--line:#2b303b;--del:#f87171;--edit:#fbbf24}}
body{margin:0;padding:24px 16px;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
main{max-width:760px;margin:0 auto}
h1{font-size:22px;margin:0 0 4px}h2{font-size:17px;margin:28px 0 10px;padding-bottom:6px;border-bottom:1px solid var(--line)}
.meta{color:var(--hint);font-size:13px;margin-bottom:8px}
.entry{background:var(--card);border-radius:14px;padding:12px 14px;margin:10px 0}
.head{display:flex;justify-content:space-between;gap:12px;font-size:13px;color:var(--hint)}
.tag{font-weight:600}.tag.deleted{color:var(--del)}.tag.edited{color:var(--edit)}
.text{white-space:pre-wrap;word-break:break-word;margin:6px 0 0}
.label{color:var(--hint);font-size:12px;margin-top:8px}
img{max-width:100%;border-radius:10px;margin-top:8px;display:block}
.omitted{color:var(--hint);font-style:italic;margin-top:8px}
"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _entry_html(e, offset_minutes, L, photo) -> str:
    event = e["event"]
    parts = [
        '<div class="entry">',
        f'<div class="head"><span class="tag {_esc(event)}">{_esc(L.get(event, event))}</span>'
        f"<span>{_esc(format_ts(e['created_at'], offset_minutes))}</span></div>",
    ]
    if event == "edited":
        if e["old_text"]:
            parts.append(
                f'<div class="label">{_esc(L["was"])}</div><p class="text">{_esc(e["old_text"])}</p>'
            )
        if e["new_text"]:
            parts.append(
                f'<div class="label">{_esc(L["became"])}</div><p class="text">{_esc(e["new_text"])}</p>'
            )
    else:
        text = e["old_text"] or e["new_text"]
        if text:
            parts.append(f'<p class="text">{_esc(text)}</p>')

    media_type = e.get("media_type")
    if media_type:
        if photo is not None:
            data = base64.b64encode(photo).decode("ascii")
            parts.append(f'<img alt="" src="data:image/jpeg;base64,{data}">')
        else:
            name = L["media"].get(media_type, media_type)
            parts.append(
                f'<div class="omitted">{_esc(name)} — {_esc(L["media_omitted"])}</div>'
            )
    parts.append("</div>")
    return "".join(parts)


def build_html(
    entries, chat_names, offset_minutes, locale, now_ts, photos=None, group_by_chat=True
) -> bytes:
    """photos: {log_id: bytes JPEG} — только для тех записей, фото которых
    нужно вшить в файл (data URI). Остальное медиа помечается как не включённое."""
    L = labels(locale)
    photos = photos or {}
    ordered = order_entries(entries, group_by_chat)

    body = [
        f"<h1>{_esc(L['title'])}</h1>",
        f'<div class="meta">{_esc(L["exported"])}: {_esc(format_ts(now_ts, offset_minutes))} · {_esc(L["total"])}: {len(ordered)}</div>',
    ]
    current_chat = object()
    for e in ordered:
        if group_by_chat and e["chat_id"] != current_chat:
            current_chat = e["chat_id"]
            body.append(
                f"<h2>{_esc(chat_label(chat_names, e['chat_id'], locale))}</h2>"
            )
        elif not group_by_chat:
            pass
        entry = _entry_html(e, offset_minutes, L, photos.get(e["log_id"]))
        if not group_by_chat:
            entry = entry.replace(
                '<div class="head">',
                f'<div class="head"><span>{_esc(chat_label(chat_names, e["chat_id"], locale))}</span>',
                1,
            )
        body.append(entry)

    document = (
        f'<!DOCTYPE html><html lang="{_esc(locale)}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{_esc(L['title'])}</title><style>{_CSS}</style></head>"
        f"<body><main>{''.join(body)}</main></body></html>"
    )
    return document.encode("utf-8")
