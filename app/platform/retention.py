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
from app.features.ai.queries import purge_old_drafts
from app.features.archive.queries import expire_archive_media, purge_archive
from app.features.autoresponder.queries import purge_autoresponder_log
from app.features.history.service import expire_history_media, purge_history
from app.features.history.service import trim_message_log

logger = logging.getLogger("bot.retention")

_INTERVAL_SECONDS = 6 * 3600
_FIRST_RUN_DELAY_SECONDS = 300


async def run_retention_once(now=None):
    now = int(now if now is not None else time.time())
    day = 86400
    stats = {}

    if settings.MEDIA_RETENTION_DAYS > 0:
        stats["media_expired"] = await expire_history_media(
            now - settings.MEDIA_RETENTION_DAYS * day
        )
    if settings.ARCHIVE_MEDIA_RETENTION_DAYS > 0:
        stats["archive_media_expired"] = await expire_archive_media(
            now - settings.ARCHIVE_MEDIA_RETENTION_DAYS * day
        )
    if settings.HISTORY_RETENTION_DAYS > 0:
        stats["history_purged"] = await purge_history(
            now - settings.HISTORY_RETENTION_DAYS * day
        )
    if settings.ARCHIVE_RETENTION_DAYS > 0:
        stats["archive_purged"] = await purge_archive(
            now - settings.ARCHIVE_RETENTION_DAYS * day
        )

    stats["autoresponder_log_purged"] = await purge_autoresponder_log(now - 30 * day)
    stats["ai_drafts_purged"] = await purge_old_drafts(now - 7 * day)
    if settings.MESSAGE_LOG_KEEP > 0:
        stats["message_log_trimmed"] = await trim_message_log(settings.MESSAGE_LOG_KEEP)
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
