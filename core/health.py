"""Замеры «здоровья» бота — общие для команды .ping и для GET /api/ping/deep."""

import asyncio
import time

from tortoise import Tortoise

STARTED_AT = time.monotonic()

# Не ждём ответа дольше этого: зависший вызов не должен вешать ни команду, ни API
_TIMEOUT_SECONDS = 5


def uptime_seconds() -> int:
    return int(time.monotonic() - STARTED_AT)


async def timed_ms(coro_factory):
    """Время выполнения корутины в миллисекундах; None — если упала или зависла."""
    started = time.perf_counter()
    try:
        await asyncio.wait_for(coro_factory(), timeout=_TIMEOUT_SECONDS)
    except Exception:
        return None
    return (time.perf_counter() - started) * 1000


async def measure_health(bot) -> dict:
    telegram_ms = await timed_ms(bot.get_me)
    db_ms = await timed_ms(
        lambda: Tortoise.get_connection("default").execute_query("SELECT 1")
    )
    return {
        "telegram_ms": None if telegram_ms is None else round(telegram_ms),
        "db_ms": None if db_ms is None else round(db_ms),
        "uptime_seconds": uptime_seconds(),
    }