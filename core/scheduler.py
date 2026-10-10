import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from core import database as db
from core.utils import log_suppressed

logger = logging.getLogger("bot.scheduler")


async def emoji_clock_tick(bot):
    owners = await db.get_active_emoji_status_owners()
    if not owners:
        return

    offsets = await db.get_timezone_offsets_for(owners)
    now_utc = datetime.now(timezone.utc)
    emoji_cache = {}

    for owner_id in owners:
        offset_minutes = offsets.get(owner_id, 180)
        local_time = now_utc + timedelta(minutes=offset_minutes)
        time_key = local_time.strftime("%H:%M")

        if time_key not in emoji_cache:
            emoji_cache[time_key] = await db.get_clock_emoji(time_key)
        custom_emoji_id = emoji_cache[time_key]
        if not custom_emoji_id:
            continue

        try:
            await bot.set_user_emoji_status(
                user_id=owner_id,
                emoji_status_custom_emoji_id=custom_emoji_id,
            )
        except (TelegramBadRequest, TelegramForbiddenError):
            logger.warning(
                "Доступ к эмодзи-статусу отозван для owner_id=%s — выключаю", owner_id
            )
            await db.set_emoji_status_granted(owner_id, False)
            await db.set_emoji_status_enabled(owner_id, False)
            try:
                await bot.send_message(
                    chat_id=owner_id,
                    text=(
                        "⚠️ Доступ к эмодзи-статусу отозван — часы в статусе "
                        "выключены. Включить заново можно в мини-приложении → Аккаунт."
                    ),
                )
            except Exception:
                log_suppressed("core/scheduler.py:51")
        except Exception:
            logger.exception("Не удалось обновить эмодзи-статус owner_id=%s", owner_id)


async def run_emoji_clock(bot):
    while True:
        now = datetime.now(timezone.utc)
        sleep_for = 60 - now.second - now.microsecond / 1_000_000
        await asyncio.sleep(max(0.0, sleep_for))
        try:
            await emoji_clock_tick(bot)
        except Exception:
            logger.exception("Сбой тика эмодзи-часов")
