import asyncio

from core.context import CommandContext
from core.registry import command

_DELAY = 0.5
_MAX_PARTS = 40


@command(
    name="split",
    module="split",
)
async def cmd_split(ctx: CommandContext):
    if not ctx.args.strip():
        await ctx.usage_error(ctx.t("split.usage"))
        return

    if " " in ctx.args:
        parts = ctx.args.split()[:_MAX_PARTS]
    else:
        parts = [x for x in ctx.args]

    await ctx.edit_command_message(parts.pop(0))

    await asyncio.sleep(_DELAY)

    for part in parts:
        await ctx.reply(part)
        await asyncio.sleep(_DELAY)
