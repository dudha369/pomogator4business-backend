from tortoise import fields
from tortoise.models import Model


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


async def is_favorite_chat(owner_id, chat_id):
    return await FavoriteChat.filter(owner_id=owner_id, chat_id=chat_id).exists()


async def toggle_favorite_chat(owner_id, chat_id):
    """Переключает пометку. Возвращает True, если чат стал избранным."""
    deleted = await FavoriteChat.filter(owner_id=owner_id, chat_id=chat_id).delete()
    if deleted:
        return False
    await FavoriteChat.get_or_create(owner_id=owner_id, chat_id=chat_id)
    return True


async def set_favorite_chat(owner_id, chat_id, favorite):
    if favorite:
        await FavoriteChat.get_or_create(owner_id=owner_id, chat_id=chat_id)
    else:
        await FavoriteChat.filter(owner_id=owner_id, chat_id=chat_id).delete()


async def list_favorite_chat_ids(owner_id):
    rows = await FavoriteChat.filter(owner_id=owner_id).values_list(
        "chat_id", flat=True
    )
    return set(rows)
