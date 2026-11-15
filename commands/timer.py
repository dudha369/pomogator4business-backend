from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from core.scheduled import schedule
from core.utils import parse_duration

_MAX_SECONDS = 24 * 3600


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

    # сначала запись в БД: если она не удалась, «таймер установлен» не показываем
    await schedule("timer", ctx.connection_id, ctx.chat_id, seconds, text=text)
    await ctx.edit_command_message(ctx.t("timer.set", time=raw_time))
