"""Короткий кэш для настроек, которые читаются на КАЖДОЕ сообщение (подключение,
выключенные модули, язык). Правки из мини-приложения и бота сбрасывают кэш сразу
(`clear_all` в функциях записи), а TTL — страховка на случай записи из другого процесса
(при деплое на секунды работают два экземпляра)."""

import copy
import functools
import time

_caches: list[dict] = []
_TTL_SECONDS = 5


def ttl_cache(func):
    store: dict = {}
    _caches.append(store)

    @functools.wraps(func)
    async def wrapper(*args):
        now = time.monotonic()
        hit = store.get(args)
        if hit is not None and hit[0] > now:
            return copy.copy(hit[1])  # копия: вызывающий может менять dict/set
        value = await func(*args)
        store[args] = (now + _TTL_SECONDS, value)
        return copy.copy(value)

    return wrapper


def clear_all() -> None:
    for store in _caches:
        store.clear()
