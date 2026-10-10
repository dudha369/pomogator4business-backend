import asyncio
import io

from PIL import Image, ImageFilter
from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputStoryContentPhoto,
)

from core.context import CommandContext
from core.registry import command
from core import database as db
from core.utils import log_suppressed

_GRID = {
    3: (3, 1),
    6: (3, 2),
    9: (3, 3),
}
_ACTIVE_PERIOD = 86400
_POST_DELAY = 1.0

_TILE_W = 1080
_TILE_H = 1920
_BLUR_RADIUS = 40


def _blur_letterbox(cell: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Вписывает cell в target_w x target_h БЕЗ обрезки содержимого — а
    пустые поля заполняет размытой растянутой версией той же cell, а не
    сплошным цветом (так делают Instagram/TikTok для контента не того
    соотношения сторон). Именно так должен выглядеть каждый тайл, чтобы
    при просмотре подряд мозаика собралась в исходное фото без потерь по
    краям."""
    cell_w, cell_h = cell.size

    # Размытый фон на весь канвас — "cover" (с запасом, лишнее обрезаем).
    bg_scale = max(target_w / cell_w, target_h / cell_h)
    bg = cell.resize(
        (round(cell_w * bg_scale), round(cell_h * bg_scale)), Image.LANCZOS
    )
    bg_left = (bg.width - target_w) // 2
    bg_top = (bg.height - target_h) // 2
    bg = bg.crop((bg_left, bg_top, bg_left + target_w, bg_top + target_h))
    bg = bg.filter(ImageFilter.GaussianBlur(_BLUR_RADIUS))

    # Резкий передний план — "contain" (без обрезки содержимого).
    fg_scale = min(target_w / cell_w, target_h / cell_h)
    fg = cell.resize(
        (round(cell_w * fg_scale), round(cell_h * fg_scale)), Image.LANCZOS
    )

    canvas = bg
    paste_x = (target_w - fg.width) // 2
    paste_y = (target_h - fg.height) // 2
    canvas.paste(fg, (paste_x, paste_y))
    return canvas


def split_image(image_bytes, parts):
    """Режет ИСХОДНОЕ фото на сетку rows x cols "как есть" (без потери
    содержимого), затем каждую получившуюся ячейку вписывает в 1080x1920
    через _blur_letterbox. Порядок тайлов — слева направо, сверху вниз.
    """
    rows, cols = _GRID[parts]
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    src_w, src_h = image.size
    cell_w = src_w // cols
    cell_h = src_h // rows

    tiles = []
    for row in range(rows):
        for col in range(cols):
            box = (
                col * cell_w,
                row * cell_h,
                src_w if col == cols - 1 else (col + 1) * cell_w,
                src_h if row == rows - 1 else (row + 1) * cell_h,
            )
            cell = image.crop(box)
            tile = _blur_letterbox(cell, _TILE_W, _TILE_H)
            buffer = io.BytesIO()
            tile.save(buffer, format="JPEG", quality=95)
            tiles.append(buffer.getvalue())
    return tiles


async def _post_tile(bot, connection_id, tile_bytes):
    content = InputStoryContentPhoto.model_construct(
        photo=BufferedInputFile(tile_bytes, filename="story.jpg")
    )
    await bot.post_story(
        business_connection_id=connection_id,
        content=content,
        active_period=_ACTIVE_PERIOD,
    )


async def _post_all(bot, connection_id, tiles):
    for tile_bytes in tiles:
        try:
            await _post_tile(bot, connection_id, tile_bytes)
        except Exception:
            log_suppressed("modules/story.py:103")
        await asyncio.sleep(_POST_DELAY)


@command(
    name="story",
    module="story",
)
async def cmd_story(ctx: CommandContext):
    target = ctx.message.reply_to_message
    if not target or not target.photo:
        await ctx.usage_error(ctx.t("story.usage_reply"))
        return

    raw_parts = ctx.args.strip()
    parts = int(raw_parts) if raw_parts.isdigit() and int(raw_parts) in _GRID else 9

    photo = target.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    buffer = await ctx.bot.download_file(file.file_path)
    tiles = split_image(buffer.read(), parts)

    await ctx.delete_command_message()

    if await db.is_autopost_enabled(ctx.connection_id):
        await _post_all(ctx.bot, ctx.connection_id, tiles)
        return

    media = [
        InputMediaPhoto(media=BufferedInputFile(tile, filename=f"tile_{i + 1}.jpg"))
        for i, tile in enumerate(tiles)
    ]
    try:
        await ctx.bot.send_media_group(
            chat_id=ctx.connection["owner_chat_id"],
            media=media,
        )
    except Exception:
        log_suppressed("modules/story.py:141")


@command(
    name="storyautopost",
    module="story",
)
async def cmd_storyautopost(ctx: CommandContext):
    enabled = await db.toggle_autopost(ctx.connection_id)
    status = ctx.t("story.status_on") if enabled else ctx.t("story.status_off")
    await ctx.edit_command_message(ctx.t("story.autopost_toggled", status=status))
