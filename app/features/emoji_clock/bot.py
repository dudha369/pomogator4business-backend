import asyncio
import logging
from datetime import UTC, datetime

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramRetryAfter,
    TelegramServerError,
)

from app.features.alerts.bot import report
from app.features.emoji_clock import DEFAULT_STYLE_ID as DEFAULT_CLOCK_STYLE
from app.features.emoji_clock.queries import (
    get_active_emoji_status_settings,
    get_clock_emoji,
    get_emoji_status_style,
    set_emoji_status_enabled,
    set_emoji_status_granted,
)
from app.features.emoji_clock.style import local_time_key as _local_time_key
from db.models.user_locale import get_timezone_offsets_for

logger = logging.getLogger("bot.scheduler")


async def _emoji_id_for(cache, time_key, style):
    """custom_emoji_id для (стиль, минута). Если пак выбранного стиля ещё не
    загружен/обновляется — подставляем стиль по умолчанию, чтобы статус не пропал."""
    for candidate in (style, DEFAULT_CLOCK_STYLE):
        key = (candidate, time_key)
        if key not in cache:
            cache[key] = await get_clock_emoji(time_key, candidate)
        if cache[key]:
            return cache[key]
    return None


# Telegram отвечает BadRequest не только когда доступ отозван: битый emoji_id или
# неверные параметры — другая причина, и часы из-за неё выключать нельзя.
_ACCESS_REVOKED_MARKERS = ("permission", "not allowed", "access", "rights", "forbidden")

# не больше стольких одновременных запросов к Telegram за тик
_TICK_CONCURRENCY = 10


def _is_access_revoked(error: Exception) -> bool:
    """Доступ к статусу действительно отозван (а не сеть, лимиты или кривой запрос)."""
    if isinstance(error, TelegramForbiddenError):
        return True
    if isinstance(error, TelegramBadRequest):
        text = (error.message or "").lower()
        return any(marker in text for marker in _ACCESS_REVOKED_MARKERS)
    return False


async def _disable_clock(owner_id):
    await set_emoji_status_granted(owner_id, False)
    await set_emoji_status_enabled(owner_id, False)
    await report(owner_id, "emoji_access_revoked")


async def _push_emoji_status(bot, owner_id, style, time_key, cache):
    custom_emoji_id = await _emoji_id_for(cache, time_key, style)
    if not custom_emoji_id:
        return

    try:
        await bot.set_user_emoji_status(
            user_id=owner_id,
            emoji_status_custom_emoji_id=custom_emoji_id,
        )
    except (TelegramNetworkError, TelegramRetryAfter, TelegramServerError) as error:
        # сеть/лимиты/5xx — временный сбой: состояние не трогаем, следующий тик через минуту
        logger.warning(
            "Эмодзи-статус owner_id=%s: временный сбой (%s), пропускаю тик",
            owner_id,
            type(error).__name__,
        )
    except (TelegramBadRequest, TelegramForbiddenError) as error:
        if _is_access_revoked(error):
            logger.warning(
                "Доступ к эмодзи-статусу отозван для owner_id=%s — выключаю", owner_id
            )
            await _disable_clock(owner_id)
        else:
            logger.warning(
                "Эмодзи-статус owner_id=%s отклонён Telegram: %s", owner_id, error
            )
    except Exception:
        logger.exception("Не удалось обновить эмодзи-статус owner_id=%s", owner_id)


async def emoji_clock_tick(bot):
    settings = await get_active_emoji_status_settings()
    if not settings:
        return

    offsets = await get_timezone_offsets_for([owner_id for owner_id, _ in settings])
    now_utc = datetime.now(UTC)
    cache = {}

    gate = asyncio.Semaphore(_TICK_CONCURRENCY)

    async def push(owner_id, style):
        time_key = _local_time_key(now_utc, offsets.get(owner_id, 180))
        async with gate:
            await _push_emoji_status(bot, owner_id, style, time_key, cache)

    # return_exceptions: сбой одного владельца не должен ронять часы остальных
    await asyncio.gather(
        *(push(owner_id, style) for owner_id, style in settings),
        return_exceptions=True,
    )


async def refresh_emoji_status(bot, owner_id):
    """Сразу применить текущую минуту (например, после смены стиля в приложении),
    не дожидаясь следующего тика."""
    style = await get_emoji_status_style(owner_id)
    offsets = await get_timezone_offsets_for([owner_id])
    time_key = _local_time_key(datetime.now(UTC), offsets.get(owner_id, 180))
    await _push_emoji_status(bot, owner_id, style, time_key, {})


async def run_emoji_clock(bot):
    while True:
        now = datetime.now(UTC)
        sleep_for = 60 - now.second - now.microsecond / 1_000_000
        await asyncio.sleep(max(0.0, sleep_for))
        try:
            await emoji_clock_tick(bot)
        except Exception:
            logger.exception("Сбой тика эмодзи-часов")
