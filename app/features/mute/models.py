from tortoise import fields
from tortoise.models import Model


class Mute(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    active = fields.BooleanField(default=False)
    until = fields.BigIntField(null=True)
    warn_limit = fields.IntField(null=True)
    warn_count = fields.IntField(default=0)
    warn_duration = fields.BigIntField(null=True)

    class Meta:
        table = "mutes"
        unique_together = (("connection_id", "chat_id"),)
