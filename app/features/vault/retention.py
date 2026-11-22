from app.features.vault import service
from app.features.vault.backfill import backfill
from app.platform.retention import retention_task
from config import settings


@retention_task("vault_keys_rewrapped")
async def rewrap(now):
    """Ротация мастер-ключа: новый ключ первым в DATA_MASTER_KEYS — и ключи владельцев
    перепаковываются сами."""
    if not service.enabled():
        return None
    return await service.rewrap_keys()


@retention_task("vault_backfilled")
async def encrypt_old_rows(now):
    """Шифрует строки, записанные до включения шифрования."""
    if not service.enabled() or settings.VAULT_BACKFILL_MAX <= 0:
        return None
    return await backfill(settings.VAULT_BACKFILL_MAX)
