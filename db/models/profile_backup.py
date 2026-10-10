from tortoise import fields
from tortoise.models import Model


class ProfileBackup(Model):
    connection_id = fields.CharField(max_length=255, pk=True)
    bio = fields.TextField(null=True)
    photo_data = fields.BinaryField(null=True)
    first_name = fields.CharField(max_length=255, null=True)
    last_name = fields.CharField(max_length=255, null=True)
    saved_at = fields.BigIntField()

    class Meta:
        table = "profile_backups"


async def save_profile_backup(
    connection_id, bio, photo_data, saved_at, first_name=None, last_name=None
):
    await ProfileBackup.update_or_create(
        connection_id=connection_id,
        defaults={
            "bio": bio,
            "photo_data": photo_data,
            "first_name": first_name,
            "last_name": last_name,
            "saved_at": saved_at,
        },
    )


async def get_profile_backup(connection_id):
    rows = await ProfileBackup.filter(connection_id=connection_id).values()
    return rows[0] if rows else None
