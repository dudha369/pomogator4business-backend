"""Создание эмодзи-паков Telegram для часов (по одному комплекту на стиль).

    python scripts/create_emoji_packs.py                 # все стили, что ещё не готовы
    python scripts/create_emoji_packs.py --style stacked # только один стиль

Скрипт возобновляемый: готовые паки пропускаются, недозагруженные
достраиваются. Уже существующие паки стиля classic (clock0..7_by_<bot>) не
пересоздаются — их картинки обновляет scripts/replace_emoji_images.py.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter
from aiogram.types import BufferedInputFile, InputSticker
from tortoise import Tortoise

from config import TORTOISE_ORM, settings
from core import database as db
from core.clock_styles import (
    CLOCK_PACK_COUNT as PACK_COUNT,
    CLOCK_PACK_SIZE as PACK_SIZE,
    CLOCK_STYLE_IDS,
    clock_pack_name,
    clock_pack_title,
)

INPUT_DIR = "assets/generated_emoji"
EMOJI_LIST = ["🕐"]
UPLOAD_DELAY = 1.0

ADMIN_USER_ID = 1218892156


def all_time_keys():
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)]


def _read_sticker_bytes(style, pack_index, time_key):
    path = os.path.join(
        INPUT_DIR, style, f"pack_{pack_index}", f"{time_key.replace(':', '-')}.png"
    )
    with open(path, "rb") as f:
        return f.read()


def _build_input_sticker(style, pack_index, time_key):
    data = _read_sticker_bytes(style, pack_index, time_key)
    return InputSticker(
        sticker=BufferedInputFile(data, filename=f"{time_key}.png"),
        format="static",
        emoji_list=EMOJI_LIST,
    )


async def _call_with_retry(coro_factory):
    while True:
        try:
            return await coro_factory()
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 1)


async def _upload_pack(bot, me, style, pack_index, chunk):
    pack_row = await db.get_clock_pack(pack_index, style)
    pack_name = clock_pack_name(style, pack_index, me.username)
    uploaded_count = pack_row["uploaded_count"] if pack_row else 0

    if uploaded_count == 0:
        first_batch = chunk[:50]
        stickers = [_build_input_sticker(style, pack_index, t) for t in first_batch]

        await _call_with_retry(
            lambda: bot.create_new_sticker_set(
                user_id=ADMIN_USER_ID,
                name=pack_name,
                title=clock_pack_title(style, pack_index),
                stickers=stickers,
                sticker_type="custom_emoji",
                needs_repainting=True,
            )
        )

        uploaded_count = len(first_batch)
        await db.upsert_clock_pack(pack_index, pack_name, uploaded_count, 0, style)
        print(f"[{style}] pack {pack_index}: создан, {uploaded_count} эмодзи")

    for time_key in chunk[uploaded_count:]:
        sticker = _build_input_sticker(style, pack_index, time_key)

        await _call_with_retry(
            lambda sticker=sticker: bot.add_sticker_to_set(
                user_id=ADMIN_USER_ID,
                name=pack_name,
                sticker=sticker,
            )
        )

        uploaded_count += 1
        await db.upsert_clock_pack(pack_index, pack_name, uploaded_count, 0, style)
        print(f"[{style}] pack {pack_index}: {uploaded_count}/{len(chunk)}")
        await asyncio.sleep(UPLOAD_DELAY)

    sticker_set = await _call_with_retry(lambda: bot.get_sticker_set(pack_name))
    for time_key, sticker in zip(chunk, sticker_set.stickers):
        await db.save_clock_emoji(time_key, pack_index, sticker.custom_emoji_id, style)

    await db.upsert_clock_pack(pack_index, pack_name, len(chunk), 1, style)
    print(
        f"[{style}] pack {pack_index}: ГОТОВ, маппинг сохранён ({len(chunk)} записей)"
    )


async def main():
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().split("\n")[0] or None
    )
    parser.add_argument("--style", choices=[*CLOCK_STYLE_IDS, "all"], default="all")
    args = parser.parse_args()
    styles = list(CLOCK_STYLE_IDS) if args.style == "all" else [args.style]

    for style in styles:
        if not os.path.isdir(os.path.join(INPUT_DIR, style)):
            print(
                f"Нет картинок стиля {style}: {INPUT_DIR}/{style}/ не найдена. "
                f"Сначала: python scripts/generate_emoji_images.py --style {style}"
            )
            return

    await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)

    bot = Bot(token=settings.BOT_TOKEN)
    try:
        me = await bot.get_me()
        print(f"Паки будут созданы от имени @{me.username}")

        times = all_time_keys()
        for style in styles:
            for pack_index in range(PACK_COUNT):
                pack_row = await db.get_clock_pack(pack_index, style)
                if pack_row and pack_row["completed"]:
                    print(f"[{style}] pack {pack_index}: уже готов, пропускаю")
                    continue

                chunk = times[pack_index * PACK_SIZE : (pack_index + 1) * PACK_SIZE]
                await _upload_pack(bot, me, style, pack_index, chunk)

            total = await db.count_clock_emojis(style)
            print(f"[{style}] в таблице соответствия: {total}/{len(times)}")
    finally:
        await bot.session.close()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
