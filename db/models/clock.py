from tortoise import fields
from tortoise.models import Model
from tortoise.transactions import in_transaction

from emoji_clock import DEFAULT_STYLE_ID as DEFAULT_CLOCK_STYLE


class ClockPack(Model):
    """Один эмодзи-пак Telegram. Пак принадлежит стилю часов (style)."""

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
    """Соответствие «стиль + минута суток -> custom_emoji_id»."""

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


async def get_clock_packs(style):
    """Паки стиля, которые сейчас в работе (по возрастанию pack_index)."""
    return await ClockPack.filter(style=style).order_by("pack_index").values()


async def get_clock_pack_counts():
    """{style: сколько паков стиля полностью загружено}. Стиль можно выбирать,
    когда счётчик равен ClockStyle.pack_count."""
    rows = await ClockPack.filter(completed=True).values_list("style", flat=True)
    counts = {}
    for style in rows:
        counts[style] = counts.get(style, 0) + 1
    return counts


async def swap_clock_style(style, packs, emoji):
    """Атомарно переключить стиль на новый комплект паков.

    packs — [(pack_index, pack_name, uploaded_count)], emoji — [(time_key,
    pack_index, custom_emoji_id)] на ВСЕ 1440 минут. Всё в одной транзакции:
    планировщик (читает таблицу каждую минуту) видит либо старый комплект, либо
    новый целиком, без «пустых» минут."""
    async with in_transaction():
        for pack_index, pack_name, uploaded_count in packs:
            await ClockPack.update_or_create(
                style=style,
                pack_index=pack_index,
                defaults={
                    "pack_name": pack_name,
                    "uploaded_count": uploaded_count,
                    "completed": True,
                },
            )
        await ClockPack.filter(style=style, pack_index__gte=len(packs)).delete()
        await ClockEmoji.bulk_create(
            [
                ClockEmoji(
                    style=style,
                    time_key=time_key,
                    pack_index=pack_index,
                    custom_emoji_id=custom_emoji_id,
                )
                for time_key, pack_index, custom_emoji_id in emoji
            ],
            on_conflict=("style", "time_key"),
            update_fields=("pack_index", "custom_emoji_id"),
        )
