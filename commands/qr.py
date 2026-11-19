import asyncio
import io

import qrcode
from aiogram.types import BufferedInputFile

from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command

# QR версии 40 вмещает ~2300 байт; в UTF-8 кириллица занимает по 2 байта
_MAX_TEXT = 1000


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

    if len(text) > _MAX_TEXT:
        await ctx.usage_error(ctx.t("qr.too_long", limit=_MAX_TEXT))
        return

    try:
        result = await asyncio.to_thread(render_qr, text)
    except Exception:  # слишком много данных для QR или сбой рендера
        await ctx.usage_error(ctx.t("qr.too_long", limit=_MAX_TEXT))
        return
    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="qr.png"),
    )
