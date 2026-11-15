from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from db.models.echo import toggle_echo


@command(name="echo", module="echo")
async def cmd_echo(ctx: CommandContext):
    enabled = await toggle_echo(ctx.connection_id, ctx.chat_id)
    status = ctx.t("echo.status_on") if enabled else ctx.t("echo.status_off")
    await ctx.edit_command_message(ctx.t("echo.toggled", status=status))
