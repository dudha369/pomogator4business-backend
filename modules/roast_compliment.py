import random

from core.context import CommandContext
from core.registry import command
from modules.type_ import typewriter

_ROAST_COUNT = 10
_COMPLIMENT_COUNT = 10


@command(name="roast", module="roast")
async def cmd_roast(ctx: CommandContext):
    index = random.randint(1, _ROAST_COUNT)
    text = ctx.t(f"roast.line_{index}")
    await typewriter(
        ctx.bot, ctx.connection, ctx.chat_id, text, "▌", ctx.message.message_id
    )


@command(name="compliment", module="compliment")
async def cmd_compliment(ctx: CommandContext):
    index = random.randint(1, _COMPLIMENT_COUNT)
    text = ctx.t(f"compliment.line_{index}")
    await typewriter(
        ctx.bot, ctx.connection, ctx.chat_id, text, "▌", ctx.message.message_id
    )
