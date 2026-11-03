"""Сборка паков одного стиля в Telegram.

Порядок эмодзи внутри пака ЗНАЧИМ: позиция в паке = слот (минута), по ней
custom_emoji_id сопоставляются со временем. Поэтому внутри одного пака эмодзи
добавляются строго по очереди, а параллелить можно только РАЗНЫЕ паки.

Возобновление без БД: если пак с таким именем уже есть в Telegram, значит он
собран этим же скриптом по порядку, и досыпаем недостающее с того места, где
остановились (len(stickers) = сколько уже загружено).
"""

import asyncio
import io

from emoji_clock.style import CLOCK_PACK_SIZE
from emoji_clock.sync.telegram import input_sticker

FIRST_BATCH = 50  # createNewStickerSet принимает до 50 стикеров сразу
LOG_EVERY = 20


def render_png_bytes(style, slots):
    """PNG-байты для слотов (CPU-работа, вызывается в потоке)."""
    result = []
    for slot in slots:
        buffer = io.BytesIO()
        style.render(slot).save(buffer, format="PNG", optimize=True)
        result.append(buffer.getvalue())
    return result


async def build_pack(tg, owner_id, bot_username, style, index, progress, log=print):
    """Собрать пак index стиля. Возвращает (имя пака, [custom_emoji_id по слотам])."""
    slots = style.pack_slots(index)
    name = style.pack_name(index, bot_username)
    tag = f"[{style.id}] пак {index + 1}/{style.pack_count}"

    images = await asyncio.to_thread(render_png_bytes, style, slots)

    existing = await tg.get_set(name)
    uploaded = len(existing.stickers) if existing else 0
    if uploaded > len(slots):
        raise RuntimeError(
            f"{tag}: в Telegram уже {uploaded} эмодзи при {len(slots)} слотах. "
            f"Пак {name} испорчен — удалите его (через @Stickers) и запустите снова"
        )
    if uploaded:
        log(f"{tag}: найден в Telegram, продолжаю с {uploaded}/{len(slots)}")
        progress.add(uploaded)

    if uploaded == 0:
        first = [
            input_sticker(slot, png) for slot, png in zip(slots[:FIRST_BATCH], images)
        ]
        await tg.create_set(owner_id, name, style.pack_title(index), first)
        uploaded = len(first)
        progress.add(uploaded)

    # строго по порядку: позиция в паке = слот
    for i in range(uploaded, len(slots)):
        await tg.add_sticker(owner_id, name, input_sticker(slots[i], images[i]))
        progress.add(1)
        if (i + 1) % LOG_EVERY == 0:
            log(f"{tag}: {i + 1}/{len(slots)}")

    final = await tg.get_set(name)
    if final is None or len(final.stickers) != len(slots):
        count = 0 if final is None else len(final.stickers)
        raise RuntimeError(f"{tag}: в Telegram {count} эмодзи, ожидалось {len(slots)}")
    return name, [sticker.custom_emoji_id for sticker in final.stickers]


def emoji_rows(style, pack_ids):
    """Строки таблицы «минута -> эмодзи» на все 1440 минут.

    pack_ids[i] — custom_emoji_id пака i по порядку слотов. Для аналоговых
    стилей 13:05 и 01:05 получают один и тот же эмодзи."""
    from emoji_clock.style import all_time_keys

    index_of = {slot: i for i, slot in enumerate(style.slots)}
    rows = []
    for time_key in all_time_keys():
        position = index_of[style.slot_for(time_key)]
        pack_index, offset = divmod(position, CLOCK_PACK_SIZE)
        rows.append((time_key, pack_index, pack_ids[pack_index][offset]))
    return rows
