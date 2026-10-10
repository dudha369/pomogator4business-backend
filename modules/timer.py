import asyncio

from core.context import CommandContext
from core.registry import command
from core.utils import parse_duration
from core.utils import log_suppressed

_MAX_SECONDS = 24 * 3600


async def _fire(bot, connection_id, chat_id, seconds, text):
    await asyncio.sleep(seconds)
    try:
        await bot.send_message(
            business_connection_id=connection_id,
            chat_id=chat_id,
            text=text,
        )
    except Exception:
        log_suppressed("modules/timer.py:18", benign=True)


@command(
    name="timer",
    module="timer",
)
async def cmd_timer(ctx: CommandContext):
    parts = ctx.args.split(maxsplit=1)
    if len(parts) < 2:
        await ctx.usage_error(ctx.t("timer.usage"))
        return

    raw_time, text = parts
    seconds = parse_duration(raw_time)
    if seconds is None or seconds <= 0 or seconds > _MAX_SECONDS:
        await ctx.reply(ctx.t("timer.invalid_time"))
        return

    await ctx.edit_command_message(ctx.t("timer.set", time=raw_time))

    asyncio.create_task(_fire(ctx.bot, ctx.connection_id, ctx.chat_id, seconds, text))
