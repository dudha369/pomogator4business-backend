from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from app.features.scheduled.service import schedule
from app.platform.utils import parse_duration_loose

_MAX_SECONDS = 24 * 3600


@command(
    name="bomb",
    aliases=["timerdel"],
    module="bomb",
)
async def cmd_bomb(ctx: CommandContext):
    target = ctx.message.reply_to_message

    if target:
        raw_time = ctx.args.strip().split()[0] if ctx.args.strip() else ""
        seconds = parse_duration_loose(raw_time)
        if seconds is None or seconds <= 0 or seconds > _MAX_SECONDS:
            await ctx.usage_error(ctx.t("bomb.usage_reply"))
            return

        await schedule(
            "bomb",
            ctx.connection_id,
            ctx.chat_id,
            seconds,
            message_id=target.message_id,
        )
        await ctx.delete_command_message()
        return

    parts = ctx.args.split(maxsplit=1)
    if len(parts) < 2:
        await ctx.usage_error(ctx.t("bomb.usage_full"))
        return

    raw_time, text = parts
    seconds = parse_duration_loose(raw_time)
    if seconds is None or seconds <= 0 or seconds > _MAX_SECONDS:
        await ctx.reply(ctx.t("bomb.invalid_time"))
        return

    await schedule(
        "bomb",
        ctx.connection_id,
        ctx.chat_id,
        seconds,
        message_id=ctx.message.message_id,
    )
    await ctx.edit_command_message(text, parse_mode=None)
