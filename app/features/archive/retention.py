from app.features.archive.queries import expire_archive_media, purge_archive
from app.platform.retention import DAY, retention_task
from config import settings


@retention_task("archive_media_expired")
async def expire_media(now):
    if settings.ARCHIVE_MEDIA_RETENTION_DAYS <= 0:
        return None
    return await expire_archive_media(now - settings.ARCHIVE_MEDIA_RETENTION_DAYS * DAY)


@retention_task("archive_purged")
async def purge_events(now):
    if settings.ARCHIVE_RETENTION_DAYS <= 0:
        return None
    return await purge_archive(now - settings.ARCHIVE_RETENTION_DAYS * DAY)
