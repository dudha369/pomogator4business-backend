from app.features.scheduled.models import ScheduledTask
from app.features.vault import service as vault

TABLE = "scheduled_tasks"


async def add_scheduled_task(
    kind, connection_id, chat_id, run_at, *, message_id=None, text=None
):
    sealed = await vault.seal_values(
        TABLE,
        await vault.owner_of(connection_id) if vault.enabled() else None,
        {"text": text},
    )
    if sealed is None:  # шифрование сломалось: без текста отправлять нечего
        raise RuntimeError("не удалось зашифровать отложенное сообщение")
    return await ScheduledTask.create(
        kind=kind,
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        run_at=run_at,
        **sealed,
    )


async def list_due_scheduled_tasks(now):
    rows = await ScheduledTask.filter(run_at__lte=now).order_by("run_at").values()
    return [
        await vault.open_row(TABLE, await vault.owner_of(r["connection_id"]), r)
        for r in rows
    ]


async def claim_scheduled_task(task_id):
    """Атомарно «забирает» задачу: True получит ровно один исполнитель (на деплое
    два процесса живут одновременно — без этого сообщение ушло бы дважды)."""
    return await ScheduledTask.filter(id=task_id).delete() == 1


async def next_scheduled_run_at():
    row = await ScheduledTask.all().order_by("run_at").first().values("run_at")
    return row["run_at"] if row else None
