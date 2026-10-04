from core.context import CommandContext
from core.registry import command

_EMOJI = {
    "dice": "🎲",
    "dart": "🎯",
    "bball": "🏀",
    "bowl": "🎳",
    "football": "⚽",
    "slot": "🎰",
}


async def _send_dice(ctx: CommandContext, key):
    await ctx.delete_command_message()
    await ctx.bot.send_dice(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        emoji=_EMOJI[key],
    )


@command(name="dice", module="dice")
async def cmd_dice(ctx: CommandContext):
    await _send_dice(ctx, "dice")


@command(name="dart", module="dice")
async def cmd_dart(ctx: CommandContext):
    await _send_dice(ctx, "dart")


@command(name="bball", module="dice")
async def cmd_bball(ctx: CommandContext):
    await _send_dice(ctx, "bball")


@command(name="bowl", module="dice")
async def cmd_bowl(ctx: CommandContext):
    await _send_dice(ctx, "bowl")


@command(name="football", module="dice")
async def cmd_football(ctx: CommandContext):
    await _send_dice(ctx, "football")


@command(name="slot", module="dice")
async def cmd_slot(ctx: CommandContext):
    await _send_dice(ctx, "slot")
