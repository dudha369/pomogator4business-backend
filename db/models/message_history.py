from tortoise import fields
from tortoise.functions import Max
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
        )  # без media_data — не тянем бинарники в память ради текстовой истории
    )
    return list(reversed(rows))


async def list_last_incoming_by_chat(connection_id):
    """По каждому чату — id и время последнего ВХОДЯЩЕГО сообщения, которое
    бот видел. Нужно для .readall: прочитать чат = прочитать это сообщение."""
    return (
        await MessageHistory.filter(connection_id=connection_id, is_owner=False)
        .group_by("chat_id")
        .annotate(last_message_id=Max("message_id"), last_at=Max("created_at"))
        .values("chat_id", "last_message_id", "last_at")
    )


async def list_recent_chats(connection_id, limit):
    """Чаты, которые бот видел (любое направление), свежие сверху."""
    return (
        await MessageHistory.filter(connection_id=connection_id)
        .group_by("chat_id")
        .annotate(last_at=Max("created_at"))
        .order_by("-last_at")
        .limit(limit)
        .values("chat_id", "last_at")
    )


async def count_messages_since(connection_id, since_ts):
    """Сколько сообщений (всего / входящих) в истории начиная с since_ts."""
    query = MessageHistory.filter(connection_id=connection_id, created_at__gte=since_ts)
    total = await query.count()
    incoming = await query.filter(is_owner=False).count()
    return total, incoming


async def purge_history(older_than_ts):
    """Полностью удаляет записи истории старше порога. Возвращает число строк."""
    return await MessageHistory.filter(created_at__lt=older_than_ts).delete()


async def expire_history_media(older_than_ts):
    """Обнуляет сохранённые байты медиа старше порога, оставляя запись и
    media_type (в архиве останется понятно, что тут было медиа)."""
    return (
        await MessageHistory.filter(
            created_at__lt=older_than_ts, media_data__not_isnull=True
        ).update(media_data=None)
    )


async def get_history_media(connection_id, chat_id, message_id):
    rows = await MessageHistory.filter(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    ).values("media_type", "media_data")
    return rows[0] if rows else None


async def list_media_flags(connection_id, pairs):
    """pairs: [(chat_id, message_id)]. Возвращает {(chat_id, message_id):
    media_type} только для сообщений, у которых сохранены байты медиа."""
    if not pairs:
        return {}
    from tortoise.expressions import Q

    condition = Q()
    for chat_id, message_id in pairs:
        condition |= Q(chat_id=chat_id, message_id=message_id)
    rows = (
        await MessageHistory.filter(
            condition, connection_id=connection_id, media_data__not_isnull=True
        ).values("chat_id", "message_id", "media_type")
    )
    return {(r["chat_id"], r["message_id"]): r["media_type"] for r in rows}
