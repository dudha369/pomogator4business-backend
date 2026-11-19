from tortoise import fields
from tortoise.models import Model


class VoiceEffect(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    effect = fields.CharField(max_length=64)

    class Meta:
        table = "voice_effects"
        unique_together = (("connection_id", "chat_id"),)
