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
