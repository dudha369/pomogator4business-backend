from tortoise import fields
from tortoise.models import Model

from emoji_clock import DEFAULT_STYLE_ID as DEFAULT_CLOCK_STYLE
from emoji_clock import normalize_style_id as normalize_clock_style


class EmojiStatusSetting(Model):
    owner_id = fields.BigIntField(pk=True, generated=False)
    granted = fields.BooleanField(default=False)
    enabled = fields.BooleanField(default=False)
    clock_style = fields.CharField(max_length=32, default=DEFAULT_CLOCK_STYLE)

    class Meta:
        table = "emoji_status_settings"


async def set_emoji_status_granted(owner_id, granted):
    obj, created = await EmojiStatusSetting.get_or_create(
        owner_id=owner_id, defaults={"granted": bool(granted), "enabled": False}
    )
    if not created:
        obj.granted = bool(granted)
        await obj.save(update_fields=["granted"])


async def is_emoji_status_granted(owner_id):
    rows = await EmojiStatusSetting.filter(owner_id=owner_id).values("granted")
    return bool(rows and rows[0]["granted"])


async def set_emoji_status_enabled(owner_id, enabled):
    obj, created = await EmojiStatusSetting.get_or_create(
        owner_id=owner_id, defaults={"granted": False, "enabled": bool(enabled)}
    )
    if not created:
        obj.enabled = bool(enabled)
        await obj.save(update_fields=["enabled"])


async def is_emoji_status_enabled(owner_id):
    rows = await EmojiStatusSetting.filter(owner_id=owner_id).values("enabled")
    return bool(rows and rows[0]["enabled"])


async def get_active_emoji_status_owners():
    return await EmojiStatusSetting.filter(enabled=True, granted=True).values_list(
        "owner_id", flat=True
    )


async def get_active_emoji_status_settings():
    """[(owner_id, clock_style), ...] для всех, у кого часы включены."""
    rows = await EmojiStatusSetting.filter(enabled=True, granted=True).values_list(
        "owner_id", "clock_style"
    )
    return [(owner_id, normalize_clock_style(style)) for owner_id, style in rows]


async def get_emoji_status_style(owner_id):
    rows = await EmojiStatusSetting.filter(owner_id=owner_id).values("clock_style")
    return (
        normalize_clock_style(rows[0]["clock_style"]) if rows else DEFAULT_CLOCK_STYLE
    )


async def set_emoji_status_style(owner_id, style):
    obj, created = await EmojiStatusSetting.get_or_create(
        owner_id=owner_id,
        defaults={"granted": False, "enabled": False, "clock_style": style},
    )
    if not created:
        obj.clock_style = style
        await obj.save(update_fields=["clock_style"])
