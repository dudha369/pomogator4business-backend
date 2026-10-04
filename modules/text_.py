import io

from PIL import Image, ImageDraw
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.imaging import draw_outlined_text, load_font, to_bytes, wrap_text
from core.media import download_message_photo
from core.registry import command


def render_meme_text(image_bytes, text):
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    draw = ImageDraw.Draw(image)

    font_size = max(24, image.width // 12)
    font = load_font(font_size)

    max_width = image.width * 0.9
    lines = wrap_text(draw, text.upper(), font, max_width)

    line_height = font_size * 1.2
    total_height = line_height * len(lines)
    y = image.height * 0.03

    for line in lines:
        text_width = draw.textlength(line, font=font)
        x = (image.width - text_width) / 2
        draw_outlined_text(
            draw, (x, y), line, font, outline_width=max(2, font_size // 12)
        )
        y += line_height

    return to_bytes(image)


@command(name="text", module="text")
async def cmd_text(ctx: CommandContext):
    target = ctx.message.reply_to_message
    photo_source = target if target and target.photo else ctx.message
    text = ctx.args.strip()

    if not photo_source or not photo_source.photo or not text:
        await ctx.usage_error(ctx.t("text.usage"))
        return

    image_bytes = await download_message_photo(ctx.bot, photo_source)
    result = render_meme_text(image_bytes, text)

    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="text.jpg"),
    )
