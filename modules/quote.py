import io

from PIL import Image, ImageDraw
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.imaging import circular_crop, load_font, to_bytes, wrap_text
from core.media import download_user_avatar
from core.registry import command


_WIDTH = 800
_PADDING = 40
_AVATAR_SIZE = 120


def render_quote(avatar_bytes, name, text):
    font_name = load_font(28)
    font_text = load_font(32)

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    text_area_width = _WIDTH - _AVATAR_SIZE - _PADDING * 3
    lines = wrap_text(measure, text, font_text, text_area_width)

    line_height = 42
    text_block_height = len(lines) * line_height
    height = max(_AVATAR_SIZE + _PADDING * 2, text_block_height + _PADDING * 2 + 50)

    canvas = Image.new("RGB", (_WIDTH, height), "#1c1c1c")
    draw = ImageDraw.Draw(canvas)

    if avatar_bytes:
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
        avatar = circular_crop(avatar_img, _AVATAR_SIZE)
        canvas.paste(avatar, (_PADDING, _PADDING), avatar)
    else:
        draw.ellipse(
            [_PADDING, _PADDING, _PADDING + _AVATAR_SIZE, _PADDING + _AVATAR_SIZE],
            fill="#444444",
        )

    text_x = _PADDING * 2 + _AVATAR_SIZE
    draw.text((text_x, _PADDING), name, font=font_name, fill="#8ab4f8")

    y = _PADDING + 46
    for line in lines:
        draw.text((text_x, y), line, font=font_text, fill="white")
        y += line_height

    return to_bytes(canvas)


@command(name="quote", aliases=["цитата"], module="quote")
async def cmd_quote(ctx: CommandContext):
    target = ctx.message.reply_to_message
    if not target:
        await ctx.usage_error(ctx.t("quote.usage_reply"))
        return

    text = target.text or target.caption
    if not text:
        await ctx.reply(ctx.t("quote.no_text"))
        return

    name = (
        target.from_user.full_name if target.from_user else ctx.t("quote.unknown_name")
    )
    avatar_bytes = None
    if target.from_user:
        avatar_bytes = await download_user_avatar(ctx.bot, target.from_user.id)

    result = render_quote(avatar_bytes, name, text)

    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="quote.jpg"),
    )
