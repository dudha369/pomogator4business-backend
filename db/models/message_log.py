from tortoise import fields
from tortoise.models import Model


class MessageLog(Model):
    log_id = fields.BigIntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    message_id = fields.BigIntField()

    class Meta:
        table = "message_log"
        indexes = (("connection_id", "chat_id", "log_id"),)


async def log_message(connection_id, chat_id, message_id):
    await MessageLog.create(
        connection_id=connection_id, chat_id=chat_id, message_id=message_id
    )


async def pop_recent_message_ids(connection_id, chat_id, count):
    rows = (
        await MessageLog.filter(connection_id=connection_id, chat_id=chat_id)
        .order_by("-log_id")
        .limit(count)
        .values("log_id", "message_id")
    )
    log_ids = [row["log_id"] for row in rows]
    message_ids = [row["message_id"] for row in rows]
    if log_ids:
        await MessageLog.filter(log_id__in=log_ids).delete()
    return message_ids


async def trim_message_log(keep):
    """Оставляет только последние `keep` записей журнала (он нужен лишь для
    .del и подобных команд, которым важны свежие сообщения). Возвращает число
    удалённых строк."""
    rows = await MessageLog.all().order_by("-log_id").offset(keep).limit(1).values_list(
        "log_id", flat=True
    )
    if not rows:
        return 0
    return await MessageLog.filter(log_id__lte=rows[0]).delete()
