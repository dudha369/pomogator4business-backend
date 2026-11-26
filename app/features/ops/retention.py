from app.features.ops.models import ErrorEvent
from app.platform.retention import retention_task
from config import settings

DAY = 86400


@retention_task("error_events_purged")
async def purge_error_events(now):
    days = settings.ERROR_EVENTS_RETENTION_DAYS
    if days <= 0:
        return None
    return await ErrorEvent.filter(last_at__lt=now - days * DAY).delete()
