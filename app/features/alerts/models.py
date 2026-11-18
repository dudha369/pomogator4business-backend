from tortoise import fields
from tortoise.models import Model


class Alert(Model):
    """Активное предупреждение владельцу. Одна строка на (owner_id, code):
    повторы только увеличивают `count`, а `notified_at` держит паузу между сообщениями.
    """

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField(db_index=True)
    code = fields.CharField(max_length=64)  # «base» или «base:subject», см. catalog.py
    kind = fields.CharField(max_length=8)  # "event" | "state"
    details = fields.JSONField(default=dict)  # dict[str, str] для подстановки в текст
    count = fields.IntField(default=1)
    created_at = fields.BigIntField()
    last_at = fields.BigIntField()  # последнее возникновение
    notified_at = fields.BigIntField()  # когда в последний раз писали владельцу
    dismissed = fields.BooleanField(
        default=False
    )  # «Понятно» — скрыто, пока не повторится

    class Meta:
        table = "alerts"
        unique_together = (("owner_id", "code"),)


class AlertMute(Model):
    """«Больше не показывать»: код полностью отключён для владельца."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    code = fields.CharField(max_length=64)

    class Meta:
        table = "alert_mutes"
        unique_together = (("owner_id", "code"),)
