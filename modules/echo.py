from core.context import CommandContext
from core.registry import command
from core import database as db


@command(name="echo", module="echo")
async def cmd_echo(ctx: CommandContext):
    enabled = await db.toggle_echo(ctx.connection_id, ctx.chat_id)
    status = ctx.t("echo.status_on") if enabled else ctx.t("echo.status_off")
    await ctx.edit_command_message(ctx.t("echo.toggled", status=status))
