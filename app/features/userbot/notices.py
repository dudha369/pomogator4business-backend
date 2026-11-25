"""Уведомления об удалении и правке из групп и каналов (источник — юзербот).

Отправляют те же функции, что и у бизнес-бота (`archive.bot`), основным ботом в личку
владельца: здесь только то, чем юзербот отличается — «подключение» без строки
Connection, заголовок с названием группы и автором, сводка массового удаления."""

import re
from types import SimpleNamespace

from aiogram import html
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from app.features.archive import service
from app.features.archive.bot.deleted import notify_album, notify_deleted
from app.features.archive.bot.edited import notify_edited
from app.features.archive.prefs import load_prefs
from app.features.userbot.burst import Batch
from app.platform.i18n import t
from app.platform.sources import userbot_connection_id
from app.platform.telegram.mentions import format_mention
from app.platform.utils import log_suppressed
from config import settings
from db.models.connection import get_connection_by_owner
from db.models.user_locale import get_locale

_USERNAME = re.compile(r"^[A-Za-z0-9_]{3,32}$")


def _bot():
    from bot_instance import bot  # лениво: bot_instance импортирует роутеры фич

    return bot


def synthetic_connection(owner_id: int) -> dict:
    """«Подключение» юзербота для сервисов архива: уведомления идут в личку владельца."""
    return {
        "connection_id": userbot_connection_id(owner_id),
        "owner_id": owner_id,
        "owner_chat_id": owner_id,
        "is_enabled": True,
    }


async def _settings_connection(owner_id: int) -> str:
    """Настройки архива и выключатель модуля живут на бизнес-подключении; без него —
    значения по умолчанию (строки для `ub:` в archive_prefs нет)."""
    connection = await get_connection_by_owner(owner_id)
    return (
        connection["connection_id"] if connection else userbot_connection_id(owner_id)
    )


async def archive_enabled(owner_id: int) -> bool:
    return await service.is_enabled(await _settings_connection(owner_id))


async def prefs_for(owner_id: int):
    return await load_prefs(await _settings_connection(owner_id))


def meta(snap: dict) -> tuple[dict, dict]:
    """(чат, автор) из raw_json, который записывает `events`."""
    raw = (snap or {}).get("raw_json") or {}
    return raw.get("chat") or {}, raw.get("from") or {}


def mention_for(chat: dict, sender: dict, chat_id: int) -> str:
    """Строка «Чат: …» в заголовке. Для группы — название и автор: без автора из
    общего чата непонятно, чьё это сообщение."""
    title = chat.get("title")
    username = chat.get("username")
    if chat.get("type") == "private":
        return format_mention(title, username, chat_id)
    name = html.quote(title or "?")
    if username and _USERNAME.match(username):
        group = f'<a href="https://t.me/{username}">{name}</a>'
    else:
        group = f"<b>{name}</b>"  # у закрытой группы ссылки на неё нет
    author = sender.get("name")
    return f"{group} · {html.quote(author)}" if author else group


def _sender(sender: dict) -> dict:
    return {
        "id": sender.get("id"),
        "username": sender.get("username"),
        "name": sender.get("name"),
    }


async def send_units(owner_id: int, chat_id: int, units: list) -> None:
    """Обычные уведомления об удалении (по одному на сообщение или альбом)."""
    bot = _bot()
    locale = await get_locale(owner_id)
    prefs = await prefs_for(owner_id)
    for unit in units:
        chat, sender = meta(unit[0][2])
        mention = mention_for(chat, sender, chat_id)
        try:
            if len(unit) == 1:
                _, entry, snap = unit[0]
                await notify_deleted(
                    bot, owner_id, locale, mention, _sender(sender), snap, entry, prefs
                )
            else:
                items = [(snap, entry) for _, entry, snap in unit]
                await notify_album(
                    bot, owner_id, locale, mention, _sender(sender), items, prefs
                )
        except Exception:
            log_suppressed("userbot/notices.py:send_units")


def archive_url(chat_id: int, started: int, last: int) -> str | None:
    """Мини-приложение на странице архива с фильтром: этот чат и этот промежуток."""
    if not settings.WEBAPP_URL:
        return None
    base = settings.WEBAPP_URL.rstrip("/")
    return f"{base}/archive?chat_id={chat_id}&date_from={started}&date_to={last + 1}&sort=asc"


async def send_summary(owner_id: int, chat_id: int, batch: Batch) -> None:
    """Одно сообщение «удалено N» с кнопкой на именно эти записи в архиве."""
    chat, _ = meta(batch.units[0][0][2])
    locale = await get_locale(owner_id)
    text = t(
        "userbot.burst.deleted",
        locale,
        chat=mention_for(chat, {}, chat_id),
        count=batch.count,
    )
    url = archive_url(chat_id, batch.started, batch.last)
    markup = None
    if url:
        markup = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t("userbot.burst.open", locale),
                        web_app=WebAppInfo(url=url),
                    )
                ]
            ]
        )
    try:
        await _bot().send_message(
            chat_id=owner_id,
            text=text,
            parse_mode="html",
            reply_markup=markup,
            disable_web_page_preview=True,
        )
    except Exception:
        log_suppressed("userbot/notices.py:send_summary")


async def flush_deleted(owner_id: int, chat_id: int, batch: Batch) -> None:
    """Окно закрылось: мало сообщений — как обычно, много — одна сводка."""
    if batch.count <= settings.USERBOT_BURST_THRESHOLD:
        await send_units(owner_id, chat_id, batch.units)
    else:
        await send_summary(owner_id, chat_id, batch)


async def send_edit(owner_id: int, msg, plan, snap: dict, previous) -> int | None:
    """Уведомление об изменении; возвращает id сообщения-уведомления."""
    chat, sender = meta(snap)
    # notify_edited берёт из «сообщения» только чат и номер
    shim = SimpleNamespace(
        chat=SimpleNamespace(id=msg.chat.id, username=msg.chat.username),
        message_id=msg.message_id,
    )
    try:
        return await notify_edited(
            _bot(),
            synthetic_connection(owner_id),
            shim,
            await get_locale(owner_id),
            mention_for(chat, sender, msg.chat.id),
            plan.change,
            plan.old,
            plan.old_entry,
            snap,
            previous,
            plan.prefs,
        )
    except Exception:
        log_suppressed("userbot/notices.py:send_edit")
        return None
