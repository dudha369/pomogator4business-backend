"""Уведомления архива в виде Rich Message. Любая неудача → False/None, и вызывающий
код шлёт обычное уведомление (`send_classic`)."""

import logging

from app.features.archive.render.classic import EMPTY, highlight_edit
from app.features.archive.render.rich import (
    build_deleted,
    build_edit_history,
    build_edited_media,
    build_location,
    can_use_rich,
)
from app.features.archive.service import edit_versions
from app.features.history.snapshot import FILE_KINDS, entry_snapshot

logger = logging.getLogger("bot.archive")


async def send(bot, chat_id, rich_message, markup):
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


async def try_deleted(
    bot, chat_id, locale, mention, snap, entry, prefs, header_key, markup
):
    if can_use_rich([(snap, entry)], prefs):
        rich = build_deleted(
            locale, mention, [snap], snap.get("forward"), prefs, header_key
        )
        if await send(bot, chat_id, rich, markup) is not None:
            return True
    if prefs.rich and prefs.location_map and snap["kind"] in ("location", "venue"):
        rich = build_location(
            locale, mention, snap, snap.get("forward"), prefs, header_key
        )
        if await send(bot, chat_id, rich, markup) is not None:
            return True
    return False


async def try_album(bot, chat_id, locale, mention, items, prefs, header_key, markup):
    """Весь удалённый альбом одним Rich (items — [(снимок, запись)])."""
    if not can_use_rich(items, prefs):
        return False
    snaps = [snap for snap, _ in items]
    forward = next((s["forward"] for s in snaps if s.get("forward")), None)
    rich = build_deleted(locale, mention, snaps, forward, prefs, header_key)
    return await send(bot, chat_id, rich, markup) is not None


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


async def try_edit_history(
    bot,
    chat_id,
    message_id,
    locale,
    mention,
    change,
    old,
    new,
    previous,
    link_kb,
    created_at,
    prefs,
    albums,
    notice_id,
    now,
):
    """Правка текста/подписи: ОДНО сообщение на всё сообщение собеседника.

    Первое уведомление отправляем, на каждую следующую правку тем же сообщением
    обновляем историю (ранние версии сворачиваются). Возвращает id уведомления."""
    versions, times = edit_versions(
        previous if prefs.edit_history else [], old, new, now, created_at
    )
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
        current_html=await highlight_edit(*versions[-2], *versions[-1]) or EMPTY,
        header_key=header_key,
        media_snaps=_history_media(new, message_id, albums, prefs),
        prefs=prefs,
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
    return await send(bot, chat_id, rich, link_kb)


async def try_edited_media(
    bot, chat_id, locale, mention, change, old, old_entry, new, prefs, link_kb
):
    """Замена файла: «было» и «стало» одним Rich, если файлы подходят."""
    if not (
        prefs.rich
        and old["kind"] in FILE_KINDS
        and new["kind"] in FILE_KINDS
        and can_use_rich([(old, old_entry), (new, None)], prefs)
    ):
        return None
    rich = build_edited_media(
        locale,
        mention,
        old,
        new,
        caption_changed=change == "media_caption",
        old_text=old["text"],
        new_text=new["text"],
    )
    return await send(bot, chat_id, rich, link_kb)
