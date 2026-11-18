from app.features.chats.models import ChatFlags, FavoriteChat, KnownChat

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


async def is_known_chat(owner_id, chat_id):
    return await KnownChat.filter(owner_id=owner_id, chat_id=chat_id).exists()


async def mark_known_chat(owner_id, chat_id):
    await KnownChat.get_or_create(owner_id=owner_id, chat_id=chat_id)
