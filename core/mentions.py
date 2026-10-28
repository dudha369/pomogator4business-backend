"""Упоминания пользователей в HTML-сообщениях бота.

В базе игр и других модулей хранятся только id пользователей. Имя и username
берутся в момент показа: из кеша, который пополняется самими апдейтами
(`remember`), а при промахе — запросом к Bot API (`get_chat`). Поэтому тексты
можно свободно менять, а смена имени пользователя в Telegram подхватывается сама.

Все функции, возвращающие строку, возвращают готовый HTML: сообщение нужно
отправлять с parse_mode="html"; прочие подставляемые в него данные — экранировать
через `escape`.
"""

import logging
import re
import time
from dataclasses import dataclass

from aiogram import html

logger = logging.getLogger("bot.mentions")

_USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
_TTL_SECONDS = 600  # столько живёт имя в кеше
_NEGATIVE_TTL_SECONDS = 60  # после неудачного запроса не долбим API целую минуту
_MAX_ENTRIES = 2000

escape = html.quote


@dataclass(frozen=True)
class Person:
    full_name: str | None
    username: str | None


# user_id -> (время истечения, Person | None); None — «запросили и не получилось»
_cache: dict[int, tuple[float, Person | None]] = {}


def format_mention(full_name, username, user_id, fallback="?") -> str:
    """HTML-ссылка на пользователя: на t.me/username, а без username — на tg://user."""
    name = escape(full_name or fallback)
    if username and _USERNAME_RE.match(username):
        return f'<a href="https://t.me/{username}">{name}</a>'
    return f'<a href="tg://user?id={int(user_id)}">{name}</a>'


def _store(user_id: int, person: Person | None, ttl: float) -> None:
    if len(_cache) >= _MAX_ENTRIES:
        now = time.monotonic()
        for key in [k for k, (exp, _) in _cache.items() if exp <= now]:
            del _cache[key]
        if len(_cache) >= _MAX_ENTRIES:  # всё ещё много — выбрасываем самые старые
            for key in sorted(_cache, key=lambda k: _cache[k][0])[: _MAX_ENTRIES // 4]:
                del _cache[key]
    _cache[user_id] = (time.monotonic() + ttl, person)


def remember(user) -> None:
    """Запоминает имя пользователя из апдейта (message.from_user, call.from_user,
    message.chat) — тогда для показа не понадобится запрос к Telegram."""
    if user is None or getattr(user, "id", None) is None:
        return
    _store(
        user.id,
        Person(getattr(user, "full_name", None), getattr(user, "username", None)),
        _TTL_SECONDS,
    )


async def resolve(bot, user_id: int) -> Person | None:
    """Имя и username пользователя: кеш → Bot API. None — узнать не удалось."""
    cached = _cache.get(user_id)
    if cached and cached[0] > time.monotonic():
        return cached[1]

    try:
        chat = await bot.get_chat(user_id)
    except Exception:
        logger.debug("get_chat(%s) не удался", user_id, exc_info=True)
        _store(user_id, None, _NEGATIVE_TTL_SECONDS)
        return None

    person = Person(chat.full_name, chat.username)
    _store(user_id, person, _TTL_SECONDS)
    return person


async def mention(bot, user_id: int, fallback: str = "?") -> str:
    """Упоминание по id. Если имя узнать не удалось — ссылка с текстом fallback
    (она всё равно кликабельна и ведёт на нужного человека)."""
    person = await resolve(bot, user_id)
    if person is None:
        return format_mention(None, None, user_id, fallback)
    return format_mention(person.full_name, person.username, user_id, fallback)


def clear_cache() -> None:
    _cache.clear()
