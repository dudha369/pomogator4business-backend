"""Проверка работоспособности бота: .ping / /ping (алиасы: .pong, .пинг).

Измеряет три вещи: время ответа Bot API, время запроса к базе данных и
задержку доставки самого сообщения-команды до бота."""

import time

from tortoise import Tortoise

from core.context import CommandContext
from core.registry import command

_STARTED_AT = time.monotonic()


def format_uptime(seconds: int, ctx: CommandContext) -> str:
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    parts = []
    if days:
        parts.append(ctx.t("ping.unit_d", n=days))
    if hours or days:
        parts.append(ctx.t("ping.unit_h", n=hours))
    parts.append(ctx.t("ping.unit_m", n=minutes))
    return " ".join(parts)


async def _timed(coro_factory):
    started = time.perf_counter()
    try:
        await coro_factory()
    except Exception:
        return None
    return (time.perf_counter() - started) * 1000


@command(name="ping", aliases=["pong", "пинг"], module="ping", scope="both")
async def cmd_ping(ctx: CommandContext):
    api_ms = await _timed(ctx.bot.get_me)
    db_ms = await _timed(
        lambda: Tortoise.get_connection("default").execute_query("SELECT 1")
    )

    # message.date имеет точность до секунды — это грубая оценка доставки
    delivery_s = max(0, int(time.time() - ctx.message.date.timestamp()))

    def ms(value):
        return ctx.t("ping.failed") if value is None else f"{value:.0f} ms"

    text = ctx.t(
        "ping.result",
        api=ms(api_ms),
        db=ms(db_ms),
        delivery=delivery_s,
        uptime=format_uptime(time.monotonic() - _STARTED_AT, ctx),
    )
    await ctx.edit_command_message(text)
