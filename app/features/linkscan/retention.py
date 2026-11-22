from app.features.linkscan.queries import purge_expired
from app.platform.retention import retention_task


@retention_task("linkscan_cache_expired")
async def expire_cache(now):
    return await purge_expired(now)
