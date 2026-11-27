from tortoise.transactions import in_transaction

from app.features.emoji_clock import DEFAULT_STYLE_ID as DEFAULT_CLOCK_STYLE
from app.features.emoji_clock import normalize_style_id as normalize_clock_style
from app.features.emoji_clock.models import ClockEmoji, ClockPack, EmojiStatusSetting


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


async def get_clock_emojis_at(time_key):
    """{style: custom_emoji_id} на минуту time_key: эмодзи для живого превью стилей."""
    rows = await ClockEmoji.filter(time_key=time_key, custom_emoji_id__not_isnull=True)
    return {row.style: row.custom_emoji_id for row in rows}


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
