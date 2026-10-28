from tortoise import fields
from tortoise.models import Model


class ReminderSettings(Model):
    """Напоминания «собеседник написал, а вы не ответили» (core/reminders.py)."""

    owner_id = fields.BigIntField(pk=True)
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


async def get_reminder_settings(owner_id):
    rows = await ReminderSettings.filter(owner_id=owner_id).values()
    return rows[0] if rows else None


async def upsert_reminder_settings(owner_id, **fields_):
    await ReminderSettings.update_or_create(owner_id=owner_id, defaults=fields_)


async def list_reminder_owner_ids():
    return await ReminderSettings.filter(enabled=True).values_list(
        "owner_id", flat=True
    )
