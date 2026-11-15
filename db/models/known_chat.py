from tortoise import fields
from tortoise.models import Model


class KnownChat(Model):
    """Собеседник, которого владелец уже "знает" — привязано к owner_id, а
    не к connection_id: переподключение бота (новый business_connection_id)
    не должно сбрасывать список и заставлять bot повторно "проверять"
    старых контактов, см. commands/scam.py."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()

    class Meta:
        table = "known_chats"
        unique_together = (("owner_id", "chat_id"),)


async def is_known_chat(owner_id, chat_id):
    return await KnownChat.filter(owner_id=owner_id, chat_id=chat_id).exists()


async def mark_known_chat(owner_id, chat_id):
    await KnownChat.get_or_create(owner_id=owner_id, chat_id=chat_id)
