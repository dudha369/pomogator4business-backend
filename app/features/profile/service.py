"""Бизнес-логика и запросы фичи «profile»."""

from app.features.profile.models import ProfileBackup


async def save_profile_backup(
    connection_id, bio, photo_data, saved_at, first_name=None, last_name=None
):
    await ProfileBackup.update_or_create(
        connection_id=connection_id,
        defaults={
            "bio": bio,
            "photo_data": photo_data,
            "first_name": first_name,
            "last_name": last_name,
            "saved_at": saved_at,
        },
    )


async def delete_profile_backup(connection_id):
    await ProfileBackup.filter(connection_id=connection_id).delete()


async def get_profile_backup(connection_id):
    rows = await ProfileBackup.filter(connection_id=connection_id).values()
    return rows[0] if rows else None
