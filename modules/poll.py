from aiogram.types import InputPollOption

from core.context import CommandContext
from core.registry import command

_MAX_OPTIONS = 10


@command(name="poll", module="poll")
async def cmd_poll(ctx: CommandContext):
    raw = ctx.args.strip()
    parts = [p.strip() for p in raw.split("|") if p.strip()]

    if len(parts) < 3:
        await ctx.usage_error(ctx.t("poll.usage"))
        return

    question = parts[0]
    options = parts[1 : _MAX_OPTIONS + 1]

    await ctx.delete_command_message()
    await ctx.bot.send_poll(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        question=question,
        options=[InputPollOption(text=option) for option in options],
        is_anonymous=False,
    )
