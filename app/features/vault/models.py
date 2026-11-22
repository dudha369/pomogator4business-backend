from tortoise import fields
from tortoise.models import Model


class OwnerKey(Model):
    """Ключ данных владельца, обёрнутый мастер-ключом. Активная — наибольшая версия;
    старые версии хранятся, пока есть записи, зашифрованные ими."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    version = fields.SmallIntField()
    wrapped_dek = fields.BinaryField()
    # какой мастер-ключ обернул DEK (ротация мастер-ключа перепаковывает эти строки)
    master_version = fields.SmallIntField()
    created_at = fields.BigIntField()

    class Meta:
        table = "owner_keys"
        unique_together = (("owner_id", "version"),)
