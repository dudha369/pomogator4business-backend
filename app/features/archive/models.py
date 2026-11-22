"""Модели архива: журнал событий и настройки оформления."""

from tortoise import fields
from tortoise.models import Model


class ArchiveLog(Model):
    log_id = fields.BigIntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField()
    event = fields.CharField(max_length=32)
    old_text = fields.TextField(null=True)
    new_text = fields.TextField(null=True)
    media_type = fields.CharField(max_length=16, null=True)
    media_mime = fields.CharField(max_length=255, null=True)
    media_name = fields.TextField(null=True)
    media_status = fields.CharField(max_length=16, null=True)
    media_data = fields.BinaryField(null=True)
    kind = fields.CharField(max_length=24, null=True)
    # автор сообщения: True — владелец, False — собеседник (Telegram не сообщает,
    # кто именно удалил, поэтому в уведомлении называем автора)
    is_owner = fields.BooleanField(default=False)
    edit_kind = fields.CharField(max_length=24, null=True)
    old_snapshot = fields.JSONField(null=True)
    new_snapshot = fields.JSONField(null=True)
    # id сообщения-уведомления в чате с ботом: его правим, а не шлём новое
    notice_message_id = fields.BigIntField(null=True)
    # версия ключа данных; NULL — открытая запись (до шифрования), см. app/features/vault
    enc_ver = fields.SmallIntField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "archive_log"
        indexes = (("connection_id", "event", "log_id"),)


class ArchivePrefs(Model):
    # Текст docstring ниже попадает в COMMENT ON TABLE и в MODELS_STATE aerich: не менять,
    # иначе `aerich migrate` увидит diff. Код настроек теперь — app/features/archive/prefs.py.
    """Как владелец хочет видеть уведомления архива (JSON, см. core/archive_prefs.py)."""

    connection_id = fields.CharField(max_length=255, pk=True)
    data = fields.JSONField(default=dict)

    class Meta:
        table = "archive_prefs"
