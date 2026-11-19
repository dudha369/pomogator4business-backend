from tortoise import fields
from tortoise.models import Model


class AiSettings(Model):
    owner_id = fields.BigIntField(pk=True, generated=False)
    enabled = fields.BooleanField(default=False)
    # draft — бот присылает владельцу черновик с кнопками; auto — отвечает сам
    mode = fields.CharField(max_length=8, default="draft")
    instructions = fields.TextField(null=True)
    history_messages = fields.IntField(default=10)
    daily_limit = fields.IntField(default=30)

    class Meta:
        table = "ai_settings"


class AiDraft(Model):
    """Черновик ответа ИИ, ожидающий решения владельца."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()
    source_message_id = fields.BigIntField()
    text = fields.TextField()
    created_at = fields.BigIntField()
    status = fields.CharField(
        max_length=16, default="pending"
    )  # pending | sent | dismissed

    class Meta:
        table = "ai_drafts"
