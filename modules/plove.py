from core.context import CommandContext
from core.registry import command
from modules.type_ import typewriter


@command(name="plove", module="plove")
async def cmd_plove(ctx: CommandContext):
    if not ctx.args.strip():
        return

    decorated = f"❤️ {ctx.args} ❤️"
    await typewriter(
        ctx.bot, ctx.connection, ctx.chat_id, decorated, "▌", ctx.message.message_id
    )
