"""Периодическая очистка разрастающихся таблиц.

- байты медиа в message_history обнуляются через MEDIA_RETENTION_DAYS;
- записи message_history удаляются через HISTORY_RETENTION_DAYS;
- записи archive_log удаляются через ARCHIVE_RETENTION_DAYS (0 = хранить вечно);
- message_log (нужен только .del и подобным) обрезается до MESSAGE_LOG_KEEP строк.

Сроки настраиваются переменными окружения (см. config.py)."""

import asyncio
import logging
import time

from config import settings
from core import database as db

logger = logging.getLogger("bot.retention")

_INTERVAL_SECONDS = 6 * 3600
_FIRST_RUN_DELAY_SECONDS = 300


async def run_retention_once(now=None):
    now = int(now if now is not None else time.time())
    day = 86400
    stats = {}

    if settings.MEDIA_RETENTION_DAYS > 0:
        stats["media_expired"] = await db.expire_history_media(
            now - settings.MEDIA_RETENTION_DAYS * day
        )
    if settings.HISTORY_RETENTION_DAYS > 0:
        stats["history_purged"] = await db.purge_history(
            now - settings.HISTORY_RETENTION_DAYS * day
        )
    if settings.ARCHIVE_RETENTION_DAYS > 0:
        stats["archive_purged"] = await db.purge_archive(
            now - settings.ARCHIVE_RETENTION_DAYS * day
        )
    if settings.MESSAGE_LOG_KEEP > 0:
        stats["message_log_trimmed"] = await db.trim_message_log(
            settings.MESSAGE_LOG_KEEP
        )
    return stats


async def run_retention_loop():
    await asyncio.sleep(_FIRST_RUN_DELAY_SECONDS)
    while True:
        try:
            stats = await run_retention_once()
            logger.info("Очистка выполнена: %s", stats)
        except Exception:
            logger.exception("Сбой очистки старых данных")
        await asyncio.sleep(_INTERVAL_SECONDS)
