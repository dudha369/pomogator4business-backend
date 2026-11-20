from app.features.autoresponder.queries import purge_autoresponder_log
from app.platform.retention import DAY, retention_task


@retention_task("autoresponder_log_purged")
async def purge_log(now):
    # строки kind="greeting" запрос не трогает: иначе приветствие ушло бы повторно
    return await purge_autoresponder_log(now - 30 * DAY)
