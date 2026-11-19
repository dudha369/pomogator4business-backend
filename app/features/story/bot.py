import asyncio

from aiogram.types import (
    BufferedInputFile,
    InputMediaPhoto,
    InputStoryContentPhoto,
)

from app.features.story.queries import is_autopost_enabled, toggle_autopost
from app.features.story.service import GRID, split_image
from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from app.platform.utils import log_suppressed

_ACTIVE_PERIOD = 86400
_POST_DELAY = 1.0


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
            log_suppressed("commands/story.py:103")
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
    parts = int(raw_parts) if raw_parts.isdigit() and int(raw_parts) in GRID else 9

    photo = target.photo[-1]
    file = await ctx.bot.get_file(photo.file_id)
    buffer = await ctx.bot.download_file(file.file_path)
    tiles = await asyncio.to_thread(split_image, buffer.read(), parts)

    await ctx.delete_command_message()

    if await is_autopost_enabled(ctx.connection_id):
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
        log_suppressed("commands/story.py:141")


@command(
    name="storyautopost",
    module="story",
)
async def cmd_storyautopost(ctx: CommandContext):
    enabled = await toggle_autopost(ctx.connection_id)
    status = ctx.t("story.status_on") if enabled else ctx.t("story.status_off")
    await ctx.edit_command_message(ctx.t("story.autopost_toggled", status=status))
