import io

from PIL import Image, ImageDraw
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.imaging import circular_crop, load_font, to_bytes, wrap_text
from core.media import download_user_avatar
from core.registry import command


_WIDTH = 800
_PADDING = 36
_AVATAR_SIZE = 90


def render_fake_card(avatar_bytes, name, handle, text, watermark):
    font_name = load_font(26)
    font_handle = load_font(20)
    font_text = load_font(30)
    font_watermark = load_font(16)

    measure = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    text_width = _WIDTH - _PADDING * 2
    lines = wrap_text(measure, text, font_text, text_width)

    header_height = _AVATAR_SIZE + _PADDING
    text_block_height = len(lines) * 40
    height = header_height + text_block_height + _PADDING * 3

    canvas = Image.new("RGB", (_WIDTH, height), "#15202b")
    draw = ImageDraw.Draw(canvas)

    if avatar_bytes:
        avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
        avatar = circular_crop(avatar_img, _AVATAR_SIZE)
        canvas.paste(avatar, (_PADDING, _PADDING), avatar)
    else:
        draw.ellipse(
            [_PADDING, _PADDING, _PADDING + _AVATAR_SIZE, _PADDING + _AVATAR_SIZE],
            fill="#3a4a58",
        )

    text_x = _PADDING * 2 + _AVATAR_SIZE
    draw.text((text_x, _PADDING), name, font=font_name, fill="white")
    draw.text((text_x, _PADDING + 34), handle, font=font_handle, fill="#8899a6")

    y = header_height + _PADDING
    for line in lines:
        draw.text((_PADDING, y), line, font=font_text, fill="white")
        y += 40

    draw.text(
        (_PADDING, height - _PADDING), watermark, font=font_watermark, fill="#5a6a78"
    )

    return to_bytes(canvas)


@command(name="fake", aliases=["фейк", "твит"], module="fake")
async def cmd_fake(ctx: CommandContext):
    target = ctx.message.reply_to_message
    raw = ctx.args.strip()

    if "|" in raw:
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) >= 3:
            name, handle, text = parts[0], parts[1], "|".join(parts[2:]).strip()
        elif len(parts) == 2:
            name, text = parts
            handle = "@" + name.lower().replace(" ", "")
        else:
            await ctx.usage_error(ctx.t("fake.usage_pipe"))
            return
        avatar_bytes = None
    elif target and target.from_user:
        name = target.from_user.full_name
        handle = (
            f"@{target.from_user.username}" if target.from_user.username else "@user"
        )
        text = raw or (target.text or target.caption or "")
        if not text:
            await ctx.reply(ctx.t("fake.no_text"))
            return
        avatar_bytes = await download_user_avatar(ctx.bot, target.from_user.id)
    else:
        await ctx.usage_error(ctx.t("fake.usage_reply"))
        return

    result = render_fake_card(avatar_bytes, name, handle, text, ctx.t("fake.watermark"))

    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="fake.jpg"),
    )
