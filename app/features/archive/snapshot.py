"""Снимок сообщения для архива: что показываем вебу и как сравниваем правки.

Сам снимок (типы, колонки, `entry_snapshot`) — в `app.features.history.snapshot`; здесь только то,
что нужно уведомлениям об удалении/правке. aiogram здесь нет."""

from app.features.history.snapshot import FILE_KINDS, MAX_DOWNLOAD_BYTES


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
