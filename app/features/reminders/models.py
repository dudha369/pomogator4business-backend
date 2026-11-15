from tortoise import fields
from tortoise.models import Model


class ReminderSettings(Model):
    """Напоминания «собеседник написал, а вы не ответили» (core/reminders.py)."""

    owner_id = fields.BigIntField(pk=True, generated=False)
    enabled = fields.BooleanField(default=False)
    hours = fields.IntField(default=4)  # через сколько часов без ответа напомнить
    # «тихие часы» — минуты от локальной полуночи владельца; None — без ограничений
    quiet_start_minutes = fields.IntField(null=True)
    quiet_end_minutes = fields.IntField(null=True)
    favorites_only = fields.BooleanField(
        default=False
    )  # напоминать только о избранных чатах

    class Meta:
        table = "reminder_settings"
