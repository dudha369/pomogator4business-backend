"""Пометка чатов прочитанными: общая логика для команды .readall и для
мини-приложения (POST /api/readall).

Бот не видит, какие чаты у владельца реально непрочитаны, поэтому работает по
своей истории: для каждого чата берётся последнее входящее сообщение, которое
бот видел, и оно помечается прочитанным (вместе со всем, что выше)."""

import asyncio
import logging
import re
import time
from dataclasses import dataclass

from aiogram.exceptions import TelegramRetryAfter

from core import database as db

logger = logging.getLogger("bot.readall")

_LAST_RE = re.compile(r"^(\d+)([hчdд])$")
_OLDER_RE = re.compile(r"^>(\d+)([hчdд])$")
_NOFAV = {"nofav", "-fav", "безизбранных", "безизбр"}


@dataclass
class ReadFilter:
    last_seconds: int | None = None  # только чаты с входящим не старше N секунд
    older_seconds: int | None = None  # только чаты, где последнее входящее старше N секунд
    exclude_fav: bool = False


def _to_seconds(amount, unit):
    return int(amount) * (86400 if unit in ("d", "д") else 3600)


def parse_filters(args):
    """Разбирает аргументы команды: `6h`, `2d`, `>24h`, `nofav`.
    Возвращает ReadFilter или None, если есть непонятный токен."""
    flt = ReadFilter()
    for token in args.lower().split():
        if token in _NOFAV:
            flt.exclude_fav = True
        elif m := _OLDER_RE.match(token):
            flt.older_seconds = _to_seconds(*m.groups())
        elif m := _LAST_RE.match(token):
            flt.last_seconds = _to_seconds(*m.groups())
        else:
            return None
    return flt


def select_chats(rows, now, favorites, flt):
    result = []
    for row in rows:
        age = now - row["last_at"]
        if flt.last_seconds is not None and age > flt.last_seconds:
            continue
        if flt.older_seconds is not None and age <= flt.older_seconds:
            continue
        if flt.exclude_fav and row["chat_id"] in favorites:
            continue
        result.append(row)
    return result


async def _read_one(bot, connection_id, row):
    for attempt in range(2):
        try:
            await bot.read_business_message(
                business_connection_id=connection_id,
                chat_id=row["chat_id"],
                message_id=row["last_message_id"],
            )
            return True
        except TelegramRetryAfter as exc:
            if attempt == 0:
                await asyncio.sleep(exc.retry_after)
                continue
            return False
        except Exception:
            logger.warning("readBusinessMessage chat=%s", row["chat_id"], exc_info=True)
            return False
    return False


async def find_chats(connection, flt, now=None):
    """Чаты, подходящие под фильтр (без прочтения) — для предпросмотра."""
    rows = await db.list_last_incoming_by_chat(connection["connection_id"])
    favorites = (
        await db.list_favorite_chat_ids(connection["owner_id"])
        if flt.exclude_fav
        else set()
    )
    return select_chats(rows, int(now if now is not None else time.time()), favorites, flt)


async def read_chats(bot, connection, flt, now=None):
    """Помечает прочитанными подходящие чаты. Возвращает
    {"matched": N, "done": N, "failed": N}."""
    chats = await find_chats(connection, flt, now)
    done = 0
    for row in chats:
        if await _read_one(bot, connection["connection_id"], row):
            done += 1
        await asyncio.sleep(0.05)  # не упираемся в лимиты Bot API
    return {"matched": len(chats), "done": done, "failed": len(chats) - done}
