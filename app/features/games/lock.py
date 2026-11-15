"""Сериализация ходов в играх: два быстрых нажатия не должны затирать друг друга
(read-modify-write в save_game). Замок на (connection_id, chat_id); процесс один
(WEB_CONCURRENCY=1), поэтому asyncio.Lock достаточно."""

import asyncio
import functools
import weakref

# слабые ссылки: замок живёт, пока его кто-то держит или ждёт, и сам исчезает
_locks: "weakref.WeakValueDictionary[tuple, asyncio.Lock]" = (
    weakref.WeakValueDictionary()
)


def game_lock(connection_id, chat_id) -> asyncio.Lock:
    key = (connection_id, chat_id)
    lock = _locks.get(key)
    if lock is None:
        lock = _locks[key] = asyncio.Lock()
    return lock


def serialized_command(handler):
    """То же для текстовых ходов-команд (.hangman, .guess, .city, .word): два быстрых
    сообщения подряд не должны читать одно и то же состояние и затирать друг друга."""

    @functools.wraps(handler)
    async def wrapper(ctx, *args, **kwargs):
        async with game_lock(ctx.connection_id, ctx.chat_id):
            return await handler(ctx, *args, **kwargs)

    return wrapper


def serialized_game(handler):
    """Декоратор callback-хендлера игры: ходы в одном чате идут строго по очереди."""

    @functools.wraps(handler)
    async def wrapper(call, *args, **kwargs):
        message = call.message
        if message is None:
            return await handler(call, *args, **kwargs)
        async with game_lock(
            getattr(message, "business_connection_id", None), message.chat.id
        ):
            return await handler(call, *args, **kwargs)

    return wrapper
