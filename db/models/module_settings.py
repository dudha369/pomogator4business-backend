from tortoise import fields
from tortoise.models import Model

from core.ttl_cache import clear_all, ttl_cache


class DisabledModule(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    module = fields.CharField(max_length=64)

    class Meta:
        table = "disabled_modules"
        unique_together = (("connection_id", "module"),)


async def disable_module(connection_id, module):
    await DisabledModule.get_or_create(connection_id=connection_id, module=module)
    clear_all()


async def enable_module(connection_id, module):
    await DisabledModule.filter(connection_id=connection_id, module=module).delete()
    clear_all()


@ttl_cache
async def list_disabled_modules(connection_id):
    modules = await DisabledModule.filter(connection_id=connection_id).values_list(
        "module", flat=True
    )
    return set(modules)
