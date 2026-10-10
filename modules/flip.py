import asyncio
import random

from core.context import CommandContext
from core.registry import command
from core.utils import log_suppressed


@command(name="flip", module="flip")
async def cmd_flip(ctx: CommandContext):
    await ctx.edit_command_message(
        '<tg-emoji emoji-id="5920267974043766795">🪙</tg-emoji>',
        parse_mode="HTML",
    )

    await asyncio.sleep(1.5)

    result = random.choice(["ОРЁЛ", "РЕШКА"])

    try:
        await ctx.edit_command_message(
            text=f"""
────────────────────
<tg-emoji emoji-id="5379600444098093058">🪙</tg-emoji> <b>Результат</b>: Выпал{'а' if result == 'РЕШКА' else ''} <b><u>{result}</u></b>! 
────────────────────""",
            parse_mode="html",
        )
    except Exception:
        log_suppressed("modules/flip.py:27", benign=True)
