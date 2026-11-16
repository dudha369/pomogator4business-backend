from tortoise import fields
from tortoise.models import Model


class MessageHistory(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField()
    is_owner = fields.BooleanField()
    text = fields.TextField(null=True)
    media_type = fields.CharField(max_length=16, null=True)
    media_data = fields.BinaryField(null=True)
    media_mime = fields.CharField(max_length=255, null=True)
    media_name = fields.CharField(max_length=255, null=True)
    media_status = fields.CharField(max_length=16, null=True)
    kind = fields.CharField(max_length=24, null=True)
    entities = fields.JSONField(null=True)
    show_caption_above = fields.BooleanField(default=False)
    has_spoiler = fields.BooleanField(default=False)
    file_id = fields.CharField(max_length=255, null=True)
    file_unique_id = fields.CharField(max_length=64, null=True)
    file_size = fields.BigIntField(null=True)
    payload = fields.JSONField(null=True)
    forward = fields.JSONField(null=True)
    raw_json = fields.JSONField(null=True)
    bot_id = fields.BigIntField(null=True)
    media_group_id = fields.CharField(max_length=64, null=True)
    # распознанный текст голосового (если владелец включил в настройках)
    transcript = fields.TextField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "message_history"
        unique_together = (("connection_id", "chat_id", "message_id"),)
        indexes = (("connection_id", "chat_id", "created_at"),)
