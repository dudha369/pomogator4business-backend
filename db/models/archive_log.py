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
    media_name = fields.CharField(max_length=255, null=True)
    media_status = fields.CharField(max_length=16, null=True)
    media_data = fields.BinaryField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "archive_log"
        indexes = (("connection_id", "event", "log_id"),)


LIST_COLUMNS = (
    "log_id",
    "connection_id",
    "chat_id",
    "message_id",
    "event",
    "old_text",
    "new_text",
    "media_type",
    "media_mime",
    "media_name",
    "media_status",
    "created_at",
)


async def log_archive_event(
    connection_id,
    chat_id,
    message_id,
    event,
    old_text,
    new_text,
    created_at,
    media_type=None,
    media_data=None,
    media_mime=None,
    media_name=None,
    media_status=None,
):
    if media_type is not None and media_status is None:
        media_status = "saved" if media_data is not None else "failed"
    await ArchiveLog.create(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        event=event,
        old_text=old_text,
        new_text=new_text,
        media_type=media_type,
        media_data=media_data,
        media_mime=media_mime,
        media_name=media_name,
        media_status=media_status,
        created_at=created_at,
    )


async def get_recent_archive(connection_id, limit):
    return (
        await ArchiveLog.filter(connection_id=connection_id)
        .order_by("-log_id")
        .limit(limit)
        .values(*LIST_COLUMNS)
    )


async def get_archive_page(
    connection_id,
    before_id,
    limit,
    event=None,
    search=None,
    chat_id=None,
    date_from=None,
    date_to=None,
    ascending=False,
):
    query = ArchiveLog.filter(connection_id=connection_id)
    if before_id is not None:
        if ascending:
            query = query.filter(log_id__gt=before_id)
        else:
            query = query.filter(log_id__lt=before_id)
    if event is not None:
        query = query.filter(event=event)
    if chat_id is not None:
        query = query.filter(chat_id=chat_id)
    if date_from is not None:
        query = query.filter(created_at__gte=date_from)
    if date_to is not None:
        query = query.filter(created_at__lte=date_to)
    if search:
        from tortoise.expressions import Q

        query = query.filter(
            Q(old_text__icontains=search) | Q(new_text__icontains=search)
        )

    ordering = "log_id" if ascending else "-log_id"
    rows = await query.order_by(ordering).limit(limit + 1).values(*LIST_COLUMNS)
    has_more = len(rows) > limit
    return rows[:limit], has_more


async def count_archive_events_since(connection_id, since_ts):
    base = ArchiveLog.filter(connection_id=connection_id, created_at__gte=since_ts)
    return {
        "deleted": await base.filter(event="deleted").count(),
        "edited": await base.filter(event="edited").count(),
    }


async def purge_archive(older_than_ts):
    return await ArchiveLog.filter(created_at__lt=older_than_ts).delete()


async def list_log_media_availability(connection_id, log_ids):
    if not log_ids:
        return set()
    return set(
        await ArchiveLog.filter(
            connection_id=connection_id,
            log_id__in=list(log_ids),
            media_data__not_isnull=True,
        ).values_list("log_id", flat=True)
    )


async def get_log_media(connection_id, log_id):
    rows = await ArchiveLog.filter(connection_id=connection_id, log_id=log_id).values(
        "log_id",
        "chat_id",
        "message_id",
        "media_type",
        "media_mime",
        "media_name",
        "media_status",
        "media_data",
    )
    return rows[0] if rows else None


async def expire_archive_media(older_than_ts):
    return await ArchiveLog.filter(
        created_at__lt=older_than_ts, media_data__not_isnull=True
    ).update(media_data=None, media_status="expired")
