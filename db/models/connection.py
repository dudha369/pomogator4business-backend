from tortoise import fields
from tortoise.models import Model

from core.ttl_cache import clear_all, ttl_cache


class Connection(Model):
    connection_id = fields.CharField(max_length=255, pk=True)
    owner_id = fields.BigIntField()
    owner_chat_id = fields.BigIntField()
    owner_name = fields.CharField(max_length=255, null=True)
    owner_username = fields.CharField(max_length=255, null=True)
    is_enabled = fields.BooleanField(default=True)
    prefix = fields.CharField(max_length=8, default=".")
    rights_json = fields.TextField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "connections"


async def upsert_connection(
    connection_id,
    owner_id,
    owner_chat_id,
    is_enabled,
    owner_name=None,
    owner_username=None,
    rights_json=None,
):
    await Connection.update_or_create(
        connection_id=connection_id,
        defaults={
            "owner_id": owner_id,
            "owner_chat_id": owner_chat_id,
            "is_enabled": bool(is_enabled),
            "owner_name": owner_name,
            "owner_username": owner_username,
            "rights_json": rights_json,
        },
    )
    clear_all()


@ttl_cache
async def get_connection(connection_id):
    rows = await Connection.filter(connection_id=connection_id).values()
    return rows[0] if rows else None


async def get_connection_by_owner(owner_id):
    rows = (
        await Connection.filter(owner_id=owner_id, is_enabled=True)
        .order_by("-created_at")
        .limit(1)
        .values()
    )
    return rows[0] if rows else None


async def set_prefix(connection_id, prefix):
    await Connection.filter(connection_id=connection_id).update(prefix=prefix)
    clear_all()
