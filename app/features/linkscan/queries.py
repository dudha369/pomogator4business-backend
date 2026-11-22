from app.features.linkscan.models import LinkscanCache, LinkscanChat, LinkscanSettings
from app.platform.ttl_cache import clear_all, ttl_cache

_DEFAULTS = {"enabled": False, "scope": "all", "external": True}


@ttl_cache
async def get_settings(owner_id):
    """Читается на каждое входящее сообщение, поэтому с коротким кэшем."""
    rows = await LinkscanSettings.filter(owner_id=owner_id).values(
        "enabled", "scope", "external"
    )
    chats = await LinkscanChat.filter(owner_id=owner_id).values_list(
        "chat_id", flat=True
    )
    return {**(rows[0] if rows else _DEFAULTS), "chats": set(chats)}


async def update_settings(owner_id, *, chats=None, **fields_):
    if fields_:
        await LinkscanSettings.update_or_create(owner_id=owner_id, defaults=fields_)
    if chats is not None:
        await LinkscanChat.filter(owner_id=owner_id).delete()
        await LinkscanChat.bulk_create(
            [LinkscanChat(owner_id=owner_id, chat_id=c) for c in dict.fromkeys(chats)]
        )
    clear_all()


async def get_cached(provider, kind, key, now):
    rows = await LinkscanCache.filter(
        provider=provider, kind=kind, key=key, expires_at__gt=now
    ).values("level", "reasons")
    return rows[0] if rows else None


async def put_cached(provider, kind, key, level, reasons, expires_at):
    await LinkscanCache.update_or_create(
        provider=provider,
        kind=kind,
        key=key,
        defaults={"level": level, "reasons": list(reasons), "expires_at": expires_at},
    )


async def purge_expired(now):
    return await LinkscanCache.filter(expires_at__lte=now).delete()
