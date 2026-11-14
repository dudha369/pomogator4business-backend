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
    run_at = fields.BigIntField(db_index=True)  # unix-секунды

    class Meta:
        table = "scheduled_tasks"


async def add_scheduled_task(
    kind, connection_id, chat_id, run_at, *, message_id=None, text=None
):
    return await ScheduledTask.create(
        kind=kind,
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        run_at=run_at,
    )


async def list_due_scheduled_tasks(now):
    return await ScheduledTask.filter(run_at__lte=now).order_by("run_at").values()


async def claim_scheduled_task(task_id):
    """Атомарно «забирает» задачу: True получит ровно один исполнитель (на деплое
    два процесса живут одновременно — без этого сообщение ушло бы дважды)."""
    return await ScheduledTask.filter(id=task_id).delete() == 1


async def next_scheduled_run_at():
    row = await ScheduledTask.all().order_by("run_at").first().values("run_at")
    return row["run_at"] if row else None
