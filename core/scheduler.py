import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

from core import database as db
from core.clock_styles import DEFAULT_CLOCK_STYLE
from core.utils import log_suppressed

logger = logging.getLogger("bot.scheduler")


async def _emoji_id_for(cache, time_key, style):
    for candidate in (style, DEFAULT_CLOCK_STYLE):
        key = (candidate, time_key)
        if key not in cache:
            cache[key] = await db.get_clock_emoji(time_key, candidate)
        if cache[key]:
            return cache[key]
    return None


async def _push_emoji_status(bot, owner_id, style, time_key, cache):
    custom_emoji_id = await _emoji_id_for(cache, time_key, style)
    if not custom_emoji_id:
        return

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


def _local_time_key(now_utc, offset_minutes):
    return (now_utc + timedelta(minutes=offset_minutes)).strftime("%H:%M")


async def emoji_clock_tick(bot):
    settings = await db.get_active_emoji_status_settings()
    if not settings:
        return

    offsets = await db.get_timezone_offsets_for([owner_id for owner_id, _ in settings])
    now_utc = datetime.now(timezone.utc)
    cache = {}

    for owner_id, style in settings:
        time_key = _local_time_key(now_utc, offsets.get(owner_id, 180))
        await _push_emoji_status(bot, owner_id, style, time_key, cache)


async def refresh_emoji_status(bot, owner_id):
    style = await db.get_emoji_status_style(owner_id)
    offsets = await db.get_timezone_offsets_for([owner_id])
    time_key = _local_time_key(datetime.now(timezone.utc), offsets.get(owner_id, 180))
    await _push_emoji_status(bot, owner_id, style, time_key, {})


async def run_emoji_clock(bot):
    while True:
        now = datetime.now(timezone.utc)
        sleep_for = 60 - now.second - now.microsecond / 1_000_000
        await asyncio.sleep(max(0.0, sleep_for))
        try:
            await emoji_clock_tick(bot)
        except Exception:
            logger.exception("Сбой тика эмодзи-часов")
