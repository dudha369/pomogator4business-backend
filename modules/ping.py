"""Проверка работоспособности бота: .ping / /ping (алиасы: .pong, .пинг).

Измеряет три вещи: время ответа Bot API, время запроса к базе данных и
задержку доставки самого сообщения-команды до бота."""

import time

from core.context import CommandContext
from core.health import measure_health
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


@command(name="ping", aliases=["pong", "пинг"], module="ping", scope="both")
async def cmd_ping(ctx: CommandContext):
    health = await measure_health(ctx.bot)

    # message.date имеет точность до секунды — это грубая оценка доставки
    delivery_s = max(0, int(time.time() - ctx.message.date.timestamp()))

    def ms(value):
        return ctx.t("ping.failed") if value is None else f"{value} ms"

    text = ctx.t(
        "ping.result",
        api=ms(health["telegram_ms"]),
        db=ms(health["db_ms"]),
        delivery=delivery_s,
        uptime=format_uptime(health["uptime_seconds"], ctx),
    )
    await ctx.edit_command_message(text)
