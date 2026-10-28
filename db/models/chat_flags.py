from tortoise import fields
from tortoise.models import Model


class ChatFlags(Model):
    """Исключения по конкретному чату: «не беспокоить» для автоответов и для ИИ.
    По owner_id, а не по подключению — не теряются при переподключении."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()
    no_autoreply = fields.BooleanField(
        default=False
    )  # ни приветствия, ни «нет на месте», ни ключевых слов, ни ИИ
    no_ai = fields.BooleanField(default=False)  # только ИИ
    no_remind = fields.BooleanField(default=False)  # не напоминать, что чат ждёт ответа

    class Meta:
        table = "chat_flags"
        unique_together = (("owner_id", "chat_id"),)


_NO_FLAGS = {"no_autoreply": False, "no_ai": False, "no_remind": False}


async def get_chat_flags(owner_id, chat_id):
    rows = await ChatFlags.filter(owner_id=owner_id, chat_id=chat_id).values(
        "no_autoreply", "no_ai", "no_remind"
    )
    return rows[0] if rows else dict(_NO_FLAGS)


async def list_chat_flags(owner_id):
    return await ChatFlags.filter(owner_id=owner_id).values(
        "chat_id", "no_autoreply", "no_ai", "no_remind"
    )


async def set_chat_flags(owner_id, chat_id, **flags):
    """Меняет только переданные флаги. Строка без включённых флагов удаляется."""
    row, _ = await ChatFlags.get_or_create(owner_id=owner_id, chat_id=chat_id)
    for key, value in flags.items():
        setattr(row, key, bool(value))
    if not (row.no_autoreply or row.no_ai or row.no_remind):
        await row.delete()
        return dict(_NO_FLAGS)
    await row.save()
    return {
        "no_autoreply": row.no_autoreply,
        "no_ai": row.no_ai,
        "no_remind": row.no_remind,
    }
