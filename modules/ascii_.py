import io

from PIL import Image, ImageFilter

from core.context import CommandContext
from core.media import download_message_photo, download_user_avatar
from core.registry import command


_BRAILLE_BASE = 0x2800
_DOT_BITS = [
    (0, 0, 0x01),
    (0, 1, 0x02),
    (0, 2, 0x04),
    (1, 0, 0x08),
    (1, 1, 0x10),
    (1, 2, 0x20),
    (0, 3, 0x40),
    (1, 3, 0x80),
]
_COLUMNS = 45
_THRESHOLD = 128


def image_to_braille(image_bytes, columns=_COLUMNS, invert=False, edge=False):
    image = Image.open(io.BytesIO(image_bytes)).convert("L")
    if edge:
        image = image.filter(ImageFilter.FIND_EDGES)

    px_width = columns * 2
    aspect = image.height / image.width
    px_height = int(px_width * aspect)
    px_height = max(4, px_height - (px_height % 4))
    image = image.resize((px_width, px_height))

    pixels = image.load()

    def lit(value):
        dark = value < _THRESHOLD
        return not dark if invert else dark

    rows_out = []
    for row in range(0, px_height, 4):
        line_chars = []
        for col in range(0, px_width, 2):
            code = _BRAILLE_BASE
            for dx, dy, bit in _DOT_BITS:
                x, y = col + dx, row + dy
                if x < px_width and y < px_height and lit(pixels[x, y]):
                    code |= bit
            line_chars.append(chr(code))
        rows_out.append("".join(line_chars))

    return "\n".join(rows_out)


@command(name="ascii", module="ascii")
async def cmd_ascii(ctx: CommandContext):
    target = ctx.message.reply_to_message
    options = ctx.args.lower().split()
    invert = "invert" in options
    edge = "edge" in options

    image_bytes = None
    if target and target.photo:
        image_bytes = await download_message_photo(ctx.bot, target)
    elif target and target.from_user:
        image_bytes = await download_user_avatar(ctx.bot, target.from_user.id)

    if not image_bytes:
        await ctx.usage_error(ctx.t("ascii.usage"))
        return

    art = image_to_braille(image_bytes, invert=invert, edge=edge)

    await ctx.edit_command_message(f"<code>{art}</code>")
