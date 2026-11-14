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


async def recent_message_log(connection_id, chat_id, count):
    """Последние `count` записей журнала как [(log_id, message_id)], БЕЗ удаления:
    стирать журнал можно только после того, как сообщения реально удалены."""
    rows = (
        await MessageLog.filter(connection_id=connection_id, chat_id=chat_id)
        .order_by("-log_id")
        .limit(count)
        .values_list("log_id", "message_id")
    )
    return [tuple(row) for row in rows]


async def forget_message_log(log_ids):
    if log_ids:
        await MessageLog.filter(log_id__in=list(log_ids)).delete()


async def trim_message_log(keep):
    """Оставляет только последние `keep` записей журнала (он нужен лишь для
    .del и подобных команд, которым важны свежие сообщения). Возвращает число
    удалённых строк."""
    rows = (
        await MessageLog.all()
        .order_by("-log_id")
        .offset(keep)
        .limit(1)
        .values_list("log_id", flat=True)
    )
    if not rows:
        return 0
    return await MessageLog.filter(log_id__lte=rows[0]).delete()
