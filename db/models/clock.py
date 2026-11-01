from tortoise import fields
from tortoise.models import Model

from core.clock_styles import DEFAULT_CLOCK_STYLE


class ClockPack(Model):
    id = fields.IntField(pk=True)
    style = fields.CharField(max_length=32, default=DEFAULT_CLOCK_STYLE)
    pack_index = fields.IntField()
    pack_name = fields.CharField(max_length=255)
    uploaded_count = fields.IntField(default=0)
    completed = fields.BooleanField(default=False)

    class Meta:
        table = "clock_packs"
        unique_together = (("style", "pack_index"),)


class ClockEmoji(Model):
    id = fields.IntField(pk=True)
    style = fields.CharField(max_length=32, default=DEFAULT_CLOCK_STYLE)
    time_key = fields.CharField(max_length=16)
    pack_index = fields.IntField()
    custom_emoji_id = fields.CharField(max_length=255, null=True)

    class Meta:
        table = "clock_emojis"
        unique_together = (("style", "time_key"),)


async def get_clock_pack(pack_index, style=DEFAULT_CLOCK_STYLE):
    rows = await ClockPack.filter(style=style, pack_index=pack_index).values()
    return rows[0] if rows else None


async def upsert_clock_pack(
    pack_index, pack_name, uploaded_count, completed, style=DEFAULT_CLOCK_STYLE
):
    await ClockPack.update_or_create(
        style=style,
        pack_index=pack_index,
        defaults={
            "pack_name": pack_name,
            "uploaded_count": uploaded_count,
            "completed": bool(completed),
        },
    )


async def save_clock_emoji(
    time_key, pack_index, custom_emoji_id, style=DEFAULT_CLOCK_STYLE
):
    await ClockEmoji.update_or_create(
        style=style,
        time_key=time_key,
        defaults={"pack_index": pack_index, "custom_emoji_id": custom_emoji_id},
    )


async def get_clock_emoji(time_key, style=DEFAULT_CLOCK_STYLE):
    rows = await ClockEmoji.filter(style=style, time_key=time_key).values(
        "custom_emoji_id"
    )
    return rows[0]["custom_emoji_id"] if rows else None


async def count_clock_emojis(style=DEFAULT_CLOCK_STYLE):
    return await ClockEmoji.filter(style=style).count()


async def get_completed_clock_styles(pack_count):
    rows = await ClockPack.filter(completed=True).values_list("style", flat=True)
    counts = {}
    for style in rows:
        counts[style] = counts.get(style, 0) + 1
    return {style for style, n in counts.items() if n >= pack_count}
