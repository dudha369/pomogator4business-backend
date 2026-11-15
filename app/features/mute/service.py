"""Бизнес-логика и запросы фичи «mute»."""

from app.features.mute.models import Mute


async def get_mute(connection_id, chat_id):
    rows = await Mute.filter(connection_id=connection_id, chat_id=chat_id).values()
    return rows[0] if rows else None


async def clear_mute(connection_id, chat_id):
    await Mute.filter(connection_id=connection_id, chat_id=chat_id).delete()


async def set_timed_mute(connection_id, chat_id, until):
    await Mute.update_or_create(
        connection_id=connection_id,
        chat_id=chat_id,
        defaults={
            "active": True,
            "until": until,
            "warn_limit": None,
            "warn_count": 0,
            "warn_duration": None,
        },
    )


async def set_warn_mute(connection_id, chat_id, warn_limit, warn_duration):
    await Mute.update_or_create(
        connection_id=connection_id,
        chat_id=chat_id,
        defaults={
            "active": False,
            "until": None,
            "warn_limit": warn_limit,
            "warn_count": 0,
            "warn_duration": warn_duration,
        },
    )


async def bump_warn_count(connection_id, chat_id, new_count):
    await Mute.filter(connection_id=connection_id, chat_id=chat_id).update(
        warn_count=new_count
    )


async def activate_from_warn(connection_id, chat_id, until):
    await Mute.filter(connection_id=connection_id, chat_id=chat_id).update(
        active=True, until=until, warn_count=0
    )
