import io

from PIL import Image, ImageDraw
from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.imaging import circular_crop
from core.media import download_message_photo, download_user_avatar
from core.registry import command

_SIZE = 200
_SQUISH_SEQUENCE = [0.0, 0.15, 0.35, 0.55, 0.35, 0.15, 0.0]


def render_pet(avatar_bytes):
    avatar_img = Image.open(io.BytesIO(avatar_bytes)).convert("RGB")
    avatar = circular_crop(avatar_img, _SIZE)

    frames = []
    for factor in _SQUISH_SEQUENCE:
        frame = Image.new("RGBA", (_SIZE, _SIZE), (30, 30, 30, 255))
        squished_h = max(20, int(_SIZE * (1 - factor * 0.45)))
        offset_y = _SIZE - squished_h
        scaled = avatar.resize((_SIZE, squished_h))
        frame.paste(scaled, (0, offset_y), scaled)

        draw = ImageDraw.Draw(frame)
        hand_y = int(offset_y * 0.6)
        hand_h = int(_SIZE * (0.28 + factor * 0.15))
        draw.ellipse(
            [_SIZE * 0.08, hand_y, _SIZE * 0.92, hand_y + hand_h],
            fill=(235, 195, 160, 255),
            outline=(120, 90, 70, 255),
            width=2,
        )
        for i in range(4):
            fx = _SIZE * (0.18 + i * 0.2)
            draw.ellipse(
                [fx, hand_y - hand_h * 0.3, fx + _SIZE * 0.12, hand_y + hand_h * 0.2],
                fill=(235, 195, 160, 255),
                outline=(120, 90, 70, 255),
                width=2,
            )

        frames.append(frame.convert("P", palette=Image.ADAPTIVE))

    buffer = io.BytesIO()
    frames[0].save(
        buffer,
        format="GIF",
        save_all=True,
        append_images=frames[1:],
        duration=60,
        loop=0,
        disposal=2,
    )
    return buffer.getvalue()


@command(name="pet", aliases=["погладить"], module="pet")
async def cmd_pet(ctx: CommandContext):
    target = ctx.message.reply_to_message

    avatar_bytes = None
    if target and target.photo:
        avatar_bytes = await download_message_photo(ctx.bot, target)
    elif target and target.from_user:
        avatar_bytes = await download_user_avatar(ctx.bot, target.from_user.id)
    else:
        avatar_bytes = await download_user_avatar(ctx.bot, ctx.connection["owner_id"])

    if not avatar_bytes:
        await ctx.answer(ctx.t("pet.no_avatar"))
        return

    gif_bytes = render_pet(avatar_bytes)

    await ctx.delete_command_message()
    await ctx.bot.send_animation(
        business_connection_id=ctx.connection_id,
        chat_id=ctx.chat_id,
        animation=BufferedInputFile(gif_bytes, filename="pet.gif"),
    )
