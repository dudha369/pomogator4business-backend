"""Замена картинок в УЖЕ существующих эмодзи-паках (имена паков не меняются).

Запуск (из корня проекта), сначала сгенерируйте картинки:

    python scripts/generate_emoji_images.py --style classic
    python scripts/replace_emoji_images.py --dry-run          # ничего не меняет
    python scripts/replace_emoji_images.py --pack 0 --limit 3 # проба на 3 эмодзи
    python scripts/replace_emoji_images.py                    # все 8 паков classic

Нужно один раз: единственный стиль, который уже существует в Telegram, — classic
(остальные создаются с нуля через scripts/create_emoji_packs.py). Параметр
--style оставлен на случай, когда понадобится перерисовать и другой стиль.

ВАЖНО про custom_emoji_id. Telegram не умеет менять картинку стикера «на месте»:
replaceStickerInSet = deleteStickerFromSet + addStickerToSet + setStickerPosition.
Новая картинка — это новый документ, а значит НОВЫЙ custom_emoji_id. Сохранить
старые id технически нельзя. Зато:
  * пак (name/title) и позиция каждого эмодзи в нём остаются прежними;
  * проект берёт id только из таблицы clock_emojis (scheduler.emoji_clock_tick
    читает её каждую минуту), поэтому «миграция» — это обновление этой таблицы.
    Скрипт делает её сам: после замены перечитывает пак и пишет свежие id.

Как скрипт не ломает работающий бот:
  * перед заменой custom_emoji_id у time_key ставится NULL — scheduler пропускает
    такие минуты (`if not custom_emoji_id: continue`) и НЕ получает ошибку от
    Telegram, которая бы выключила эмодзи-статус у пользователей;
  * id обновляются в БД каждые REFRESH_EVERY замен и в конце (даже при Ctrl+C);
  * прогресс хранится в assets/generated_emoji/.replace_progress.json
    (time_key -> sha1 картинки), поэтому скрипт можно прерывать и запускать снова,
    а при перегенерации картинок заменятся только изменившиеся.
"""

import argparse
import asyncio
import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiogram import Bot
from aiogram.types import InputSticker, BufferedInputFile
from tortoise import Tortoise

from config import TORTOISE_ORM, settings
from core import database as db
from core.clock_styles import CLOCK_STYLE_IDS, DEFAULT_CLOCK_STYLE
from scripts.create_emoji_packs import (
    ADMIN_USER_ID,
    EMOJI_LIST,
    INPUT_DIR,
    PACK_COUNT,
    PACK_SIZE,
    _call_with_retry,
    _read_sticker_bytes,
    all_time_keys,
)

PROGRESS_PATH = os.path.join(
    INPUT_DIR, ".replace_progress.json"
)  # ключ: style/time_key
REPLACE_DELAY = 1.0  # пауза между заменами, чтобы не ловить flood-limit
REFRESH_EVERY = 15  # как часто перечитывать пак и обновлять id в БД


def _load_progress():
    try:
        with open(PROGRESS_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_progress(progress):
    tmp = PROGRESS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(progress, f)
    os.replace(tmp, PROGRESS_PATH)


def _sha1(data):
    return hashlib.sha1(data).hexdigest()


def _input_sticker(time_key, data):
    return InputSticker(
        sticker=BufferedInputFile(data, filename=f"{time_key}.png"),
        format="static",
        emoji_list=EMOJI_LIST,
    )


async def _fetch_stickers(bot, pack_name):
    sticker_set = await _call_with_retry(lambda: bot.get_sticker_set(pack_name))
    return list(sticker_set.stickers)


async def _reconcile(bot, style, pack_index, pack_name, chunk):
    """Источник правды — сам пак в Telegram: пишем в БД id по позициям."""
    stickers = await _fetch_stickers(bot, pack_name)
    if len(stickers) != len(chunk):
        raise RuntimeError(
            f"pack {pack_index}: в Telegram {len(stickers)} эмодзи, ожидалось {len(chunk)}"
        )
    for time_key, sticker in zip(chunk, stickers):
        await db.save_clock_emoji(time_key, pack_index, sticker.custom_emoji_id, style)
    return stickers


async def _check_order(style, pack_index, chunk, stickers):
    """Страховка: порядок в паке должен совпадать с таблицей clock_emojis.
    Замена сохраняет позицию, так что при совпадении 00:00 останется 00:00."""
    ids_in_pack = [s.custom_emoji_id for s in stickers]
    for position, time_key in enumerate(chunk):
        db_id = await db.get_clock_emoji(time_key, style)
        if db_id and db_id != ids_in_pack[position] and db_id in ids_in_pack:
            raise RuntimeError(
                f"pack {pack_index}: {time_key} в БД указывает на другую позицию "
                f"пака (ожидалась {position}). Остановка — порядок не совпадает."
            )


async def _replace_pack(
    bot, style, pack_index, pack_name, chunk, progress, args, budget
):
    stickers = await _fetch_stickers(bot, pack_name)
    if len(stickers) != len(chunk):
        raise RuntimeError(
            f"pack {pack_index}: в Telegram {len(stickers)} эмодзи, ожидалось {len(chunk)}"
        )
    await _check_order(style, pack_index, chunk, stickers)

    images = {tk: _read_sticker_bytes(style, pack_index, tk) for tk in chunk}
    todo = [
        (pos, tk)
        for pos, tk in enumerate(chunk)
        if args.force or progress.get(f"{style}/{tk}") != _sha1(images[tk])
    ]
    if budget is not None:
        todo = todo[:budget]

    print(f"pack {pack_index} ({pack_name}): к замене {len(todo)} из {len(chunk)}")
    if args.dry_run or not todo:
        return 0, 0

    old_ids = {tk: stickers[pos].custom_emoji_id for pos, tk in todo}
    done = 0
    try:
        for n, (pos, time_key) in enumerate(todo, start=1):
            old_sticker = stickers[pos]
            # пока идёт замена, scheduler пропускает эту минуту, а не падает
            await db.save_clock_emoji(time_key, pack_index, None, style)

            await _call_with_retry(
                lambda old=old_sticker, tk=time_key: bot.replace_sticker_in_set(
                    user_id=ADMIN_USER_ID,
                    name=pack_name,
                    old_sticker=old.file_id,
                    sticker=_input_sticker(tk, images[tk]),
                )
            )
            progress[f"{style}/{time_key}"] = _sha1(images[time_key])
            _save_progress(progress)
            done += 1
            print(f"pack {pack_index}: {n}/{len(todo)} ({time_key})")

            if n % REFRESH_EVERY == 0:
                stickers = await _reconcile(bot, style, pack_index, pack_name, chunk)
            await asyncio.sleep(REPLACE_DELAY)
    finally:
        # даже при ошибке/Ctrl+C возвращаем в БД актуальные id (вместо NULL)
        stickers = await _reconcile(bot, style, pack_index, pack_name, chunk)

    changed = sum(1 for pos, tk in todo if stickers[pos].custom_emoji_id != old_ids[tk])
    print(
        f"pack {pack_index}: заменено {done}, новых custom_emoji_id: {changed}, "
        f"БД обновлена"
    )
    return done, changed


async def main():
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().split("\n")[0] or None
    )
    parser.add_argument("--dry-run", action="store_true", help="только показать план")
    parser.add_argument("--style", choices=CLOCK_STYLE_IDS, default=DEFAULT_CLOCK_STYLE)
    parser.add_argument("--pack", type=int, help="обработать только этот pack_index")
    parser.add_argument("--limit", type=int, help="максимум замен за запуск (проба)")
    parser.add_argument(
        "--force", action="store_true", help="заменить всё, игнорируя прогресс"
    )
    args = parser.parse_args()

    style = args.style
    if not os.path.isdir(os.path.join(INPUT_DIR, style)):
        print(
            f"Нет картинок: {INPUT_DIR}/{style}/. Сначала: scripts/generate_emoji_images.py --style {style}"
        )
        return

    await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)
    bot = Bot(token=settings.BOT_TOKEN)
    try:
        times = all_time_keys()
        progress = _load_progress()
        budget = args.limit
        total_done = total_changed = 0

        pack_indexes = [args.pack] if args.pack is not None else range(PACK_COUNT)
        for pack_index in pack_indexes:
            pack_row = await db.get_clock_pack(pack_index, style)
            if not pack_row or not pack_row["completed"]:
                print(f"pack {pack_index}: не создан/не завершён — пропускаю")
                continue

            chunk = times[pack_index * PACK_SIZE : (pack_index + 1) * PACK_SIZE]
            done, changed = await _replace_pack(
                bot,
                style,
                pack_index,
                pack_row["pack_name"],
                chunk,
                progress,
                args,
                budget,
            )
            total_done += done
            total_changed += changed
            if budget is not None:
                budget -= done
                if budget <= 0:
                    break

        total_mapped = await db.count_clock_emojis(style)
        print(
            f"Итого заменено: {total_done}, новых id: {total_changed}. "
            f"В таблице соответствия: {total_mapped}/{len(times)}"
        )
    finally:
        await bot.session.close()
        await Tortoise.close_connections()


if __name__ == "__main__":
    asyncio.run(main())
