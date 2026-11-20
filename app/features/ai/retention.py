from app.features.ai.queries import purge_old_drafts
from app.platform.retention import DAY, retention_task


@retention_task("ai_drafts_purged")
async def purge_drafts(now):
    return await purge_old_drafts(now - 7 * DAY)
