from tortoise import fields
from tortoise.models import Model


class OwnerPlan(Model):
    """Тариф владельца. Нет строки или срок истёк — действует free (см. service.plan_of)."""

    owner_id = fields.BigIntField(pk=True, generated=False)
    plan = fields.CharField(max_length=16)  # free | pro | max (plans.PLAN_NAMES)
    expires_at = fields.BigIntField(null=True)  # NULL — без срока
    source = fields.CharField(max_length=16, default="free")
    # free | admin | payment | referral | promo

    class Meta:
        table = "owner_plans"


class UsageCounter(Model):
    """Счётчик событий за окно (сутки по UTC). Состояния (чаты, зеркала) не хранятся:
    их считает вызывающий по своим таблицам и передаёт в `limits.check(current=…)`."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    metric = fields.CharField(max_length=32)
    period_start = fields.BigIntField(db_index=True)  # начало окна, секунды UTC
    value = fields.IntField(default=0)

    class Meta:
        table = "usage_counters"
        unique_together = (("owner_id", "metric", "period_start"),)
