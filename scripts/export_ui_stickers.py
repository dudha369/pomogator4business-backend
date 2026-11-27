"""Скачивает файлы стикеров интерфейса из реестра в папку: для офлайн-экрана фронтенда.

Запуск (из папки бэкенда, BOT_TOKEN берётся из .env):
    uv run python scripts/export_ui_stickers.py ..\\frontend\\src\\assets\\stickers
Файлы получат имена `<имя из реестра>.<tgs|webm|webp>`. Всё, что лежит в этой папке
фронтенда, входит в сборку и показывается без сети; лишнее удалите перед сборкой."""

import asyncio
import sys
from pathlib import Path

from aiogram import Bot

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.platform.media import (
    StickerNotInSet,
    download_custom_emoji,
    download_set_sticker,
)
from app.platform.ui_stickers import REGISTRY
from config import settings

EXTENSIONS = {
    "application/x-tgsticker": "tgs",
    "video/webm": "webm",
    "image/webp": "webp",
}


async def export(bot, out_dir: Path, names=None) -> dict[str, str]:
    """{имя: файл или причина отказа}. Ничего не бросает на одном стикере."""
    await asyncio.to_thread(out_dir.mkdir, parents=True, exist_ok=True)
    result = {}
    for name in names or REGISTRY:
        ref = REGISTRY[name]
        try:
            if ref.emoji_id:
                found = await download_custom_emoji(bot, ref.emoji_id)
            else:
                found = await download_set_sticker(bot, ref.set_name, ref.unique_id)
        except StickerNotInSet:
            result[name] = "нет в наборе: проверьте строку реестра"
            continue
        if found is None:
            result[name] = "Telegram не отдал файл"
            continue
        data, mime = found
        path = out_dir / f"{name}.{EXTENSIONS[mime]}"
        await asyncio.to_thread(path.write_bytes, data)
        result[name] = f"{path.name} ({len(data)} байт)"
    return result


async def main(out_dir: str) -> None:
    bot = Bot(token=settings.BOT_TOKEN)
    try:
        for name, outcome in (await export(bot, Path(out_dir))).items():
            print(f"{name}: {outcome}")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    asyncio.run(main(sys.argv[1]))
