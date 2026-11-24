from app.features.limits import queries
from app.features.limits.plans import WINDOW_SECONDS
from app.platform.retention import retention_task

KEEP_DAYS = 40


@retention_task("usage_counters_purged")
async def purge_counters(now):
    return await queries.purge_before(now - KEEP_DAYS * WINDOW_SECONDS)
