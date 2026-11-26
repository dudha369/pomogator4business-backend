from tortoise import fields
from tortoise.models import Model


class ErrorEvent(Model):
    """Журнал ошибок: одна строка на отпечаток. Содержимого переписок здесь нет по
    построению (см. scrub.py), поэтому таблица не шифруется. Время — секунды UTC."""

    id = fields.BigIntField(pk=True)
    fingerprint = fields.CharField(max_length=40, unique=True)
    component = fields.CharField(max_length=24)
    kind = fields.CharField(max_length=80)
    place = fields.CharField(
        max_length=160
    )  # файл:строка функция (последнее вхождение)
    severity = fields.SmallIntField(default=0)  # 0 обычная, 1 критичная
    count = fields.IntField(default=1)
    first_at = fields.BigIntField()
    last_at = fields.BigIntField(db_index=True)
    first_build = fields.CharField(max_length=12, default="")
    last_build = fields.CharField(max_length=12, default="")
    sample = fields.TextField(default="")
    notified_at = fields.BigIntField(null=True)
    notified_count = fields.IntField(default=0)  # значение count на момент оповещения
    acked_at = fields.BigIntField(null=True)  # «Понятно»
    muted_until = fields.BigIntField(null=True)  # «Заглушить на сутки»

    class Meta:
        table = "error_events"
