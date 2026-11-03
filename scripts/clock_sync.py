"""Часы в эмодзи-статусе: одна команда на всё.

    uv run python scripts/clock_sync.py                       # все стили
    uv run python scripts/clock_sync.py --style analog_disc   # только эти стили
    uv run python scripts/clock_sync.py --dry-run             # показать план, ничего не менять
    uv run python scripts/clock_sync.py --preview             # картинка-превью (без Telegram и БД)
    uv run python scripts/clock_sync.py --export-samples DIR  # PNG-превью стилей для мини-приложения

Что делает: проверяет каждый стиль; если паков нет или они собраны из старой
версии дизайна (revision), собирает новые (все паки стиля параллельно), одним
действием переключает на них базу и удаляет старые. Прервали — запустите ещё
раз, продолжит с того же места. Если всё актуально, ничего не делает.

Изменили дизайн стиля? Увеличьте revision в emoji_clock/styles/<стиль>.py и
запустите команду. Остальное она сделает сама.
"""

import argparse
import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from emoji_clock import STYLE_IDS, STYLES  # noqa: E402


def parse_args():
    doc = (__doc__ or "").strip().split("\n")[0] or None
    parser = argparse.ArgumentParser(description=doc)
    parser.add_argument(
        "--style", nargs="+", choices=STYLE_IDS, help="какие стили (по умолчанию все)"
    )
    parser.add_argument("--dry-run", action="store_true", help="только показать план")
    parser.add_argument(
        "--preview",
        nargs="?",
        const="emoji_clock_preview.png",
        metavar="ФАЙЛ",
        help="сохранить контрольный лист стилей и выйти (Telegram и БД не нужны)",
    )
    parser.add_argument(
        "--export-samples",
        metavar="ПАПКА",
        help="сохранить по PNG на стиль (для public/clock-styles во фронтенде) и выйти",
    )
    parser.add_argument(
        "--keep-old", action="store_true", help="не удалять старые паки"
    )
    parser.add_argument(
        "--delete-delay", type=int, default=None, help="сек до удаления старых паков"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=None,
        help="паков одновременно (по умолчанию 8)",
    )
    parser.add_argument(
        "--owner-id", type=int, default=None, help="Telegram id владельца наборов"
    )
    return parser.parse_args()


async def sync(styles, args):
    from aiogram import Bot
    from tortoise import Tortoise

    from config import TORTOISE_ORM, settings
    from core import database as db
    from emoji_clock.sync import runner

    await Tortoise.init(config=TORTOISE_ORM)
    bot = Bot(token=settings.BOT_TOKEN)
    try:
        return await runner.run(
            bot,
            db,
            styles,
            owner_id=args.owner_id
            or int(os.getenv("CLOCK_OWNER_ID", runner.DEFAULT_OWNER_ID)),
            concurrency=args.concurrency or runner.DEFAULT_CONCURRENCY,
            dry_run=args.dry_run,
            keep_old=args.keep_old,
            delete_delay=(
                runner.DEFAULT_DELETE_DELAY
                if args.delete_delay is None
                else args.delete_delay
            ),
        )
    finally:
        await bot.session.close()
        await Tortoise.close_connections()


def main():
    args = parse_args()
    styles = [s for s in STYLES if not args.style or s.id in args.style]

    if args.preview or args.export_samples:
        from emoji_clock.sync import preview

        if args.preview:
            preview.save_contact_sheet(styles, args.preview)
            print(f"Превью: {args.preview}")
        if args.export_samples:
            for path in preview.export_samples(styles, args.export_samples):
                print(f"Сохранено: {path}")
        return

    ok = asyncio.run(sync(styles, args))
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
