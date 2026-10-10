from tortoise import fields
from tortoise.models import Model


class CommandAlias(Model):
    """Пользовательский алиас команды: `.п` → profile. Привязан к owner_id."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    alias = fields.CharField(max_length=32)
    command = fields.CharField(max_length=64)

    class Meta:
        table = "command_aliases"
        unique_together = (("owner_id", "alias"),)


async def list_command_aliases(owner_id):
    return await CommandAlias.filter(owner_id=owner_id).order_by("id").values(
        "alias", "command"
    )


async def count_command_aliases(owner_id):
    return await CommandAlias.filter(owner_id=owner_id).count()


async def get_command_alias(owner_id, alias):
    rows = await CommandAlias.filter(owner_id=owner_id, alias=alias).values_list(
        "command", flat=True
    )
    return rows[0] if rows else None


async def add_command_alias(owner_id, alias, command):
    await CommandAlias.create(owner_id=owner_id, alias=alias, command=command)


async def delete_command_alias(owner_id, alias):
    return bool(await CommandAlias.filter(owner_id=owner_id, alias=alias).delete())
