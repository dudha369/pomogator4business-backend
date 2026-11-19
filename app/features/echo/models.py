from tortoise import fields
from tortoise.models import Model


class EchoChat(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()

    class Meta:
        table = "echo_chats"
        unique_together = (("connection_id", "chat_id"),)
