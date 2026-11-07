from tortoise import fields
from tortoise.models import Model


class ArchivePrefs(Model):
    """Как владелец хочет видеть уведомления архива (JSON, см. core/archive_prefs.py)."""

    connection_id = fields.CharField(max_length=255, pk=True)
    data = fields.JSONField(default=dict)

    class Meta:
        table = "archive_prefs"


async def get_archive_prefs_data(connection_id):
    row = await ArchivePrefs.get_or_none(connection_id=connection_id)
    return row.data if row else {}


async def save_archive_prefs_data(connection_id, data):
    await ArchivePrefs.update_or_create(
        connection_id=connection_id, defaults={"data": data}
    )
