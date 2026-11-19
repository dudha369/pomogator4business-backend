from app.features.story.models import StoryAutopost


async def is_autopost_enabled(connection_id):
    rows = await StoryAutopost.filter(connection_id=connection_id).values("enabled")
    return bool(rows and rows[0]["enabled"])


async def toggle_autopost(connection_id):
    enabled = await is_autopost_enabled(connection_id)
    if enabled:
        await StoryAutopost.filter(connection_id=connection_id).update(enabled=False)
    else:
        await StoryAutopost.update_or_create(
            connection_id=connection_id, defaults={"enabled": True}
        )
    return not enabled
