from tortoise import fields
from tortoise.models import Model


class MessageHistory(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField()
    is_owner = fields.BooleanField()
    text = fields.TextField(null=True)
    media_type = fields.CharField(max_length=16, null=True)
    media_data = fields.BinaryField(null=True)
    created_at = fields.BigIntField()

    class Meta:
        table = "message_history"
        unique_together = (("connection_id", "chat_id", "message_id"),)
        indexes = (("connection_id", "chat_id", "created_at"),)


async def save_history(
    connection_id,
    chat_id,
    message_id,
    is_owner,
    text,
    created_at,
    media_type=None,
    media_data=None,
):
    obj, created = await MessageHistory.get_or_create(
        connection_id=connection_id,
        chat_id=chat_id,
        message_id=message_id,
        defaults={
            "is_owner": bool(is_owner),
            "text": text,
            "media_type": media_type,
            "media_data": media_data,
            "created_at": created_at,
        },
    )
    if not created:
        obj.text = text
        update_fields = ["text"]
        if media_type is not None:
            obj.media_type = media_type
            obj.media_data = media_data
            update_fields += ["media_type", "media_data"]
        await obj.save(update_fields=update_fields)


async def get_history_text(connection_id, chat_id, message_id):
    rows = await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).values("text")
    return rows[0]["text"] if rows else None


async def get_history_entry(connection_id, chat_id, message_id):
    rows = await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).values()
    return rows[0] if rows else None


async def delete_history(connection_id, chat_id, message_id):
    await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).delete()


async def has_other_messages(connection_id, chat_id, exclude_message_id):
    return (
        await MessageHistory.filter(connection_id=connection_id, chat_id=chat_id)
        .exclude(message_id=exclude_message_id)
        .exists()
    )


async def get_recent_history(connection_id, chat_id, limit):
    rows = (
        await MessageHistory.filter(connection_id=connection_id, chat_id=chat_id)
        .order_by("-created_at")
        .limit(limit)
        .values(
            "id",
            "connection_id",
            "chat_id",
            "message_id",
            "is_owner",
            "text",
            "media_type",
            "created_at",
        )
    )
    return list(reversed(rows))
