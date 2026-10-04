import io
import math
import random

from PIL import Image, ImageDraw
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.imaging import load_font, to_bytes, to_sepia, wrap_text
from core.media import download_message_photo, download_user_avatar
from core.registry import command


_CANVAS_SIZE = (900, 1200)
_PHOTO_SIZE = 640


def render_wanted(image_bytes, name, charge):
    photo = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    photo = photo.resize((_PHOTO_SIZE, _PHOTO_SIZE))
    photo = to_sepia(photo)

    canvas = Image.new("RGB", _CANVAS_SIZE, "#e8d6a8")
    draw = ImageDraw.Draw(canvas)

    draw.rectangle(
        [15, 15, _CANVAS_SIZE[0] - 15, _CANVAS_SIZE[1] - 15], outline="#3a2a1a", width=6
    )

    title_font = load_font(90, serif=True)
    title = "WANTED"
    title_width = draw.textlength(title, font=title_font)
    draw.text(
        ((_CANVAS_SIZE[0] - title_width) / 2, 40),
        title,
        font=title_font,
        fill="#3a2a1a",
    )

    sub_font = load_font(30, serif=True)
    sub = "DEAD OR ALIVE"
    sub_width = draw.textlength(sub, font=sub_font)
    draw.text(
        ((_CANVAS_SIZE[0] - sub_width) / 2, 145), sub, font=sub_font, fill="#3a2a1a"
    )

    photo_x = (_CANVAS_SIZE[0] - _PHOTO_SIZE) // 2
    photo_y = 210
    canvas.paste(photo, (photo_x, photo_y))
    draw.rectangle(
        [
            photo_x - 5,
            photo_y - 5,
            photo_x + _PHOTO_SIZE + 5,
            photo_y + _PHOTO_SIZE + 5,
        ],
        outline="#3a2a1a",
        width=5,
    )

    name_font = load_font(46, serif=True)
    name_width = draw.textlength(name, font=name_font)
    name_y = photo_y + _PHOTO_SIZE + 30
    draw.text(
        ((_CANVAS_SIZE[0] - name_width) / 2, name_y),
        name,
        font=name_font,
        fill="#3a2a1a",
    )

    charge_font = load_font(26, serif=True)
    charge_lines = wrap_text(draw, charge, charge_font, _CANVAS_SIZE[0] * 0.8)
    y = name_y + 65
    for line in charge_lines:
        line_width = draw.textlength(line, font=charge_font)
        draw.text(
            ((_CANVAS_SIZE[0] - line_width) / 2, y),
            line,
            font=charge_font,
            fill="#3a2a1a",
        )
        y += 34

    reward = f"REWARD ${random.randint(1, 999)},000"
    reward_font = load_font(50, serif=True)
    reward_width = draw.textlength(reward, font=reward_font)
    draw.text(
        ((_CANVAS_SIZE[0] - reward_width) / 2, y + 30),
        reward,
        font=reward_font,
        fill="#3a2a1a",
    )

    seal_center = (_CANVAS_SIZE[0] - 140, _CANVAS_SIZE[1] - 160)
    draw.ellipse(
        [
            seal_center[0] - 70,
            seal_center[1] - 70,
            seal_center[0] + 70,
            seal_center[1] + 70,
        ],
        outline="#8a1a1a",
        width=5,
    )
    seal_font = load_font(18, serif=True)
    for i, letter in enumerate("SHERIFF"):
        angle = math.radians(-90 + i * (360 / 14))
        x = seal_center[0] + 55 * math.cos(angle)
        y2 = seal_center[1] + 55 * math.sin(angle)
        draw.text((x, y2), letter, font=seal_font, fill="#8a1a1a", anchor="mm")

    return to_bytes(canvas)


@command(name="wanted", aliases=["розыск"], module="wanted")
async def cmd_wanted(ctx: CommandContext):
    target = ctx.message.reply_to_message
    charge = ctx.args.strip() or ctx.t("wanted.default_charge")

    if target and target.photo:
        image_bytes = await download_message_photo(ctx.bot, target)
        name = (target.from_user.full_name if target.from_user else "UNKNOWN").upper()
    else:
        user = target.from_user if target and target.from_user else None
        user_id = user.id if user else ctx.chat_id  # фолбэк — собеседник чата
        image_bytes = await download_user_avatar(ctx.bot, user_id)
        name = (user.full_name if user else "UNKNOWN").upper()

    if not image_bytes:
        await ctx.usage_error(ctx.t("wanted.usage"))
        return

    result = render_wanted(image_bytes, name, charge.upper())

    await ctx.delete_command_message()
    await ctx.bot.send_photo(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        photo=BufferedInputFile(result, filename="wanted.jpg"),
    )
