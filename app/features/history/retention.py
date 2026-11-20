import asyncio

from app.features.history.service import (
    expire_history_media,
    expire_message_log,
    purge_history,
    scrub_raw_json,
    trim_message_log,
)
from app.platform.retention import DAY, retention_task
from config import settings

# потолок за один проход: очистка старых строк идёт порциями и не держит БД долго
_MAX_SCRUB_BATCHES = 50


@retention_task("media_expired")
async def expire_media(now):
    if settings.MEDIA_RETENTION_DAYS <= 0:
        return None
    return await expire_history_media(now - settings.MEDIA_RETENTION_DAYS * DAY)


@retention_task("history_purged")
async def purge_messages(now):
    if settings.HISTORY_RETENTION_DAYS <= 0:
        return None
    return await purge_history(now - settings.HISTORY_RETENTION_DAYS * DAY)


@retention_task("message_log_expired")
async def expire_log(now):
    if settings.MESSAGE_LOG_RETENTION_DAYS <= 0:
        return None
    return await expire_message_log(now - settings.MESSAGE_LOG_RETENTION_DAYS * DAY)


@retention_task("message_log_trimmed")
async def trim_log(now):
    if settings.MESSAGE_LOG_KEEP <= 0:
        return None
    return await trim_message_log(settings.MESSAGE_LOG_KEEP)


@retention_task("raw_json_scrubbed")
async def scrub_legacy_raw_json(now):
    """Обнуляет raw_json у текста и файлов (новые строки его уже не получают)."""
    batch = settings.RAW_JSON_SCRUB_BATCH
    if batch <= 0:
        return None
    total = 0
    for _ in range(_MAX_SCRUB_BATCHES):
        done = await scrub_raw_json(batch)
        total += done
        if done < batch:
            break
        await asyncio.sleep(0)
    return total
