import io

from PIL import Image, ImageDraw
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.imaging import load_font, to_bytes, wrap_text
from core.media import download_message_photo
from core.registry import command


_BORDER = 40
_INNER_BORDER = 4
_GAP = 30


def render_demotivator(image_bytes, title, subtitle):
    photo = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    max_photo_width = 900
    if photo.width > max_photo_width:
        ratio = max_photo_width / photo.width
        photo = photo.resize((max_photo_width, int(photo.height * ratio)))

    canvas_width = photo.width + _BORDER * 2
    frame_height = photo.height + _BORDER * 2 + _INNER_BORDER * 2

    title_font = load_font(48, serif=True)
    subtitle_font = load_font(28, serif=True)

    temp_draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    title_lines = (
        wrap_text(temp_draw, title, title_font, canvas_width * 0.9) if title else []
    )
    subtitle_lines = (
        wrap_text(temp_draw, subtitle, subtitle_font, canvas_width * 0.9)
        if subtitle
        else []
    )

    text_height = 0
    if title_lines:
        text_height += len(title_lines) * 58 + _GAP
    if subtitle_lines:
        text_height += len(subtitle_lines) * 36 + _GAP

    canvas_height = frame_height + text_height + _GAP

    canvas = Image.new("RGB", (canvas_width, canvas_height), "black")
    draw = ImageDraw.Draw(canvas)

    frame_x = _BORDER
    frame_y = _BORDER
    draw.rectangle(
        [
            frame_x - _INNER_BORDER,
            frame_y - _INNER_BORDER,
            frame_x + photo.width + _INNER_BORDER,
            frame_y + photo.height + _INNER_BORDER,
        ],
        outline="white",
        width=_INNER_BORDER,
    )
    canvas.paste(photo, (frame_x, frame_y))

    y = frame_y + photo.height + _INNER_BORDER + _GAP
    for line in title_lines:
        width = draw.textlength(line, font=title_font)
        draw.text(((canvas_width - width) / 2, y), line, font=title_font, fill="white")
        y += 58

    if title_lines and subtitle_lines:
        y += _GAP - 10

    for line in subtitle_lines:
        width = draw.textlength(line, font=subtitle_font)
        draw.text(
            ((canvas_width - width) / 2, y), line, font=subtitle_font, fill="white"
        )
        y += 36

    return to_bytes(canvas)


@command(name="dem", aliases=["дем", "демотиватор"], module="dem")
async def cmd_dem(ctx: CommandContext):
    target = ctx.message.reply_to_message
    photo_source = target if target and target.photo else ctx.message

    if not photo_source or not photo_source.photo:
        await ctx.usage_error(ctx.t("dem.usage_reply"))
        return

    raw = ctx.args.strip()
    if "|" in raw:
        title, subtitle = [part.strip() for part in raw.split("|", maxsplit=1)]
    else:
        title, subtitle = raw, ""

    if not title:
        await ctx.usage_error(ctx.t("dem.usage_format"))
        return

    image_bytes = await download_message_photo(ctx.bot, photo_source)
    result = render_demotivator(image_bytes, title, subtitle)

    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="demotivator.jpg"),
    )
