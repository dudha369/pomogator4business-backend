from app.features.archive.queries import (
    expire_archive_media,
    expire_connections_media,
    logged_connection_ids,
    purge_archive,
    purge_connections_before,
)
from app.features.limits.plans import retention
from app.features.limits.service import plan_of
from app.features.vault import service as vault
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


@retention_task("archive_plan_expired")
async def expire_by_plan(now):
    """Срок хранения по тарифу владельца: записи старше `retention_days` удаляются,
    файлы старше `retention_media_days` — обнуляются (запись остаётся). Администратор
    и планы без срока не затрагиваются."""
    by_owner: dict[int, list[str]] = {}
    for connection_id in await logged_connection_ids():
        if (owner := await vault.owner_of(connection_id)) is not None:
            by_owner.setdefault(owner, []).append(connection_id)
    total = 0
    for owner, connection_ids in by_owner.items():
        text_days, media_days = retention((await plan_of(owner))["plan"])
        if media_days is not None:
            total += await expire_connections_media(
                connection_ids, now - media_days * DAY
            )
        if text_days is not None:
            total += await purge_connections_before(
                connection_ids, now - text_days * DAY
            )
    return total
