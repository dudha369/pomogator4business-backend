import io

import qrcode
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.registry import command


def render_qr(text):
    img = qrcode.make(text)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@command(name="qr", module="qr")
async def cmd_qr(ctx: CommandContext):
    text = ctx.args.strip()
    if not text:
        await ctx.usage_error(ctx.t("qr.usage"))
        return

    result = render_qr(text)
    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="qr.png"),
    )
