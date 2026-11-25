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
    media_name = fields.TextField(null=True)
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
    # версия ключа данных; NULL — открытая запись (до шифрования), см. app/features/vault
    enc_ver = fields.SmallIntField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "message_history"
        unique_together = (("connection_id", "chat_id", "message_id"),)
        indexes = (
            # удаления без chat_id (личные чаты и малые группы юзербота): ищем по номеру
            ("connection_id", "message_id"),
            ("connection_id", "chat_id", "created_at"),
            # окна статистики и напоминаний: connection_id + created_at >= …
            ("connection_id", "created_at"),
        )


class MessageLog(Model):
    log_id = fields.BigIntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField()
    # unix-секунды; NULL — запись старого формата (очищается только по лимиту числа)
    created_at = fields.BigIntField(null=True)

    class Meta:
        table = "message_log"
        indexes = (("connection_id", "chat_id", "log_id"),)


class ChatArchiveRule(Model):
    """Правило архива для одного чата владельца (общее для бизнес-бота и юзербота).

    Строка хранит только отклонение от умолчаний (`history.rules.default_rule`):
    личные чаты бизнес-бота включены без строки, всё остальное выключено."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()
    kind = fields.CharField(max_length=16)  # private | group | supergroup | channel
    enabled = fields.BooleanField(default=False)
    media_enabled = fields.BooleanField(
        default=False
    )  # сохранять файлы байтами (юзербот)
    notify = fields.BooleanField(
        default=True
    )  # присылать уведомления об удалении и правке
    created_at = fields.BigIntField()
    updated_at = fields.BigIntField()

    class Meta:
        table = "chat_archive_rules"
        unique_together = (("owner_id", "chat_id"),)
