from app.features.echo.queries import is_echo_enabled, toggle_echo
from app.features.history.service import log_message
from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command


@command(name="echo", module="echo")
async def cmd_echo(ctx: CommandContext):
    enabled = await toggle_echo(ctx.connection_id, ctx.chat_id)
    status = ctx.t("echo.status_on") if enabled else ctx.t("echo.status_off")
    await ctx.edit_command_message(ctx.t("echo.toggled", status=status))


async def echo_step(handler, message, data):
    """Middleware: в чате с включённым эхо собеседнику отвечаем его же текстом и
    останавливаем цепочку (команды собеседника не выполняются)."""
    inc = data["inc"]
    if inc.is_owner or not inc.enabled("echo"):
        return await handler(message, data)
    if not await is_echo_enabled(inc.connection_id, inc.chat_id):
        return await handler(message, data)
    if inc.text:
        sent = await inc.bot.send_message(
            business_connection_id=inc.connection_id, chat_id=inc.chat_id, text=inc.text
        )
        await log_message(inc.connection_id, inc.chat_id, sent.message_id)
    return None
