import random

from core.context import CommandContext
from core.registry import command

_ANSWER_COUNT = 12


@command(name="8ball", module="eightball")
async def cmd_8ball(ctx: CommandContext):
    args = ctx.args.strip()

    if not args:
        await ctx.delete_command_message()
        await ctx.usage_error(ctx.t("eightball.usage"))
        return

    index = random.randint(1, _ANSWER_COUNT)
    await ctx.edit_command_message(
        f"""
<blockquote>{args}</blockquote>
────────────────────
🎱 Шар говорит: <b>{ctx.t(f'eightball.answer_{index}')}</b>
────────────────────""",
        parse_mode="html",
    )
