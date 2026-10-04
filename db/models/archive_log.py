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
    created_at = fields.BigIntField()

    class Meta:
        table = "archive_log"


async def log_archive_event(
    connection_id, chat_id, message_id, event, old_text, new_text, created_at
):
    await ArchiveLog.create(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        event=event,
        old_text=old_text,
        new_text=new_text,
        created_at=created_at,
    )


async def get_recent_archive(connection_id, limit):
    return (
        await ArchiveLog.filter(connection_id=connection_id)
        .order_by("-log_id")
        .limit(limit)
        .values()
    )


async def get_archive_page(connection_id, before_id, limit):
    query = ArchiveLog.filter(connection_id=connection_id)
    if before_id is not None:
        query = query.filter(log_id__lt=before_id)
    rows = await query.order_by("-log_id").limit(limit + 1).values()
    has_more = len(rows) > limit
    return rows[:limit], has_more
