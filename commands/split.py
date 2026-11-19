import asyncio

from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command

_DELAY = 0.5
_MAX_PARTS = 40


@command(
    name="split",
    module="split",
    aliases=["words"],
)
async def cmd_split(ctx: CommandContext):
    if not ctx.args.strip():
        await ctx.usage_error(ctx.t("split.usage"))
        return

    parts = ctx.args.split()[:_MAX_PARTS] if " " in ctx.args else list(ctx.args)

    await ctx.edit_command_message(parts.pop(0), parse_mode=None)

    await asyncio.sleep(_DELAY)

    for part in parts:
        await ctx.reply(part, parse_mode=None)
        await asyncio.sleep(_DELAY)
