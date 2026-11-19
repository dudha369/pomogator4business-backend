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


class FavoriteChat(Model):
    """Чат, который владелец пометил «избранным» (команда .fav).

    Привязано к owner_id, а не к connection_id — как known_chats: при
    переподключении бота (новый business_connection_id) список не теряется.
    Используется фильтром `nofav` в .readall."""

    id = fields.IntField(pk=True)
    owner_id = fields.BigIntField()
    chat_id = fields.BigIntField()

    class Meta:
        table = "favorite_chats"
        unique_together = (("owner_id", "chat_id"),)


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
