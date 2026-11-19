from app.features.mirror.models import MirrorBot


async def save_mirror(owner_id, token_encrypted, bot_id, bot_username, created_at):
    await MirrorBot.update_or_create(
        owner_id=owner_id,
        defaults={
            "token_encrypted": token_encrypted,
            "bot_id": bot_id,
            "bot_username": bot_username,
            "created_at": created_at,
            "is_active": True,
        },
    )


async def get_mirror(owner_id):
    rows = await MirrorBot.filter(owner_id=owner_id).values()
    return rows[0] if rows else None


async def get_all_active_mirrors():
    return await MirrorBot.filter(is_active=True).values()


async def delete_mirror(owner_id):
    await MirrorBot.filter(owner_id=owner_id).delete()
