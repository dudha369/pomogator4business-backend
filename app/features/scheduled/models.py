from tortoise import fields
from tortoise.models import Model


class ScheduledTask(Model):
    """Отложенное действие (.timer / .bomb): переживает рестарт и сон Render."""

    id = fields.IntField(pk=True)
    kind = fields.CharField(max_length=16)  # "timer" | "bomb"
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField(null=True)  # bomb: что удалить
    text = fields.TextField(null=True)  # timer: что отправить
    enc_ver = fields.SmallIntField(null=True)  # см. app/features/vault
    run_at = fields.BigIntField(db_index=True)  # unix-секунды

    class Meta:
        table = "scheduled_tasks"
