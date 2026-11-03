"""Часы в эмодзи-статусе: стили и рендер, имена паков, БД, синхронизация, API."""

import types

import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from aiogram.methods import GetStickerSet
from PIL import Image, ImageChops

from core import database as db
from emoji_clock import STYLES, ClockStyle, all_time_keys, get_style, pack_revision
from emoji_clock.sync import runner
from emoji_clock.sync.builder import emoji_rows

# ----------------------------- стили и рендер -------------------------------


def ink(image):
    """Маска закрашенного (альфа > 50%), только Pillow."""
    return image.getchannel("A").point(lambda a: 255 if a > 127 else 0)


@pytest.mark.parametrize("style", STYLES, ids=lambda s: s.id)
def test_style_renders_valid_custom_emoji(style):
    for slot in (style.slots[0], style.sample, style.slots[-1]):
        image = style.render(slot)
        assert image.size == (100, 100) and image.mode == "RGBA"
        box = ink(image).getbbox()
        assert box is not None
        left, top, right, bottom = box
        # картинка занимает почти весь холст и не вылезает за него
        assert right - left >= 60 and bottom - top >= 40


@pytest.mark.parametrize("style", STYLES, ids=lambda s: s.id)
def test_pack_names_are_valid_for_telegram(style):
    import re

    for index in range(style.pack_count):
        name = style.pack_name(index, "Pomogator4Business_Bot")
        assert re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,63}", name)
        assert "__" not in name and name.endswith("_by_pomogator4business_bot")
        assert pack_revision(name) == style.revision


def test_legacy_pack_names_have_revision_zero():
    assert pack_revision("clock1_by_pomogator4business_bot") == 0
    assert pack_revision("clock_solid1_by_pomogator_app") == 0
    assert pack_revision("clock_disc_digits_v3_2_by_pomogator_app") == 3


def test_slots_and_packs_cover_the_day():
    digital, analog = get_style("solid"), get_style("analog")
    assert (len(digital.slots), digital.pack_count) == (1440, 8)
    assert (len(analog.slots), analog.pack_count) == (720, 4)
    assert sum(len(digital.pack_slots(i)) for i in range(8)) == 1440
    assert analog.slot_for("13:05") == "01:05" and analog.slot_for("00:00") == "00:00"
    assert digital.slot_for("13:05") == "13:05"
    assert len(all_time_keys()) == 1440


def test_analog_hands_follow_time():
    style = get_style("analog_disc")
    assert (
        style.render("01:05").tobytes()
        == style.render(style.slot_for("13:05")).tobytes()
    )
    assert (
        len({style.render(slot).tobytes() for slot in ("03:00", "03:30", "06:00")}) == 3
    )


def margins(mask):
    """(слева, справа) от краёв маски до закрашенного."""
    left, _, right, _ = mask.getbbox()
    return left, mask.width - right


@pytest.mark.parametrize("style_id", ["stacked", "solid", "disc_digits", "classic"])
def test_digits_are_centered_horizontally(style_id):
    """Раньше цифры уезжали вправо на 1-2 px (ячейки считались, а не чернила)."""
    style = get_style(style_id)
    worst = 0.0
    for slot in ("00:18", "11:11", "08:47", "23:59", "12:34", "17:07", "20:08"):
        mask = ink(style.render(slot))
        left, top, right, bottom = mask.getbbox()
        body = mask.crop((left, top, right, bottom))
        w, h = body.size
        if style_id in ("solid", "disc_digits"):  # цифры вырезаны: ищем «дыры»
            x0, y0, x1, y1 = int(w * 0.18), int(h * 0.18), int(w * 0.82), int(h * 0.82)
            holes = ImageChops.invert(body).crop((x0, y0, x1, y1))
            hl, _, hr, _ = holes.getbbox()
            offset = abs((x0 + hl) - (w - (x0 + hr))) / 2
        elif style_id == "classic":  # внутри рамки
            inner = mask.crop((left + 7, top + 7, right - 7, bottom - 7))
            offset = abs(margins(inner)[0] - margins(inner)[1]) / 2
        else:
            offset = abs(margins(mask)[0] - margins(mask)[1]) / 2
        worst = max(worst, offset)
    assert worst <= 1.0, f"{style_id}: цифры смещены на {worst}px"


# ----------------------------------- БД -------------------------------------


async def test_swap_replaces_a_style_atomically(database):
    await db.upsert_clock_pack(0, "clock0_by_old", 180, True, "t")
    await db.upsert_clock_pack(1, "clock1_by_old", 180, True, "t")
    await db.save_clock_emoji("00:00", 0, "old-id", "t")
    assert await db.get_clock_pack_counts() == {"t": 2}

    emoji = [(tk, 0, f"new-{tk}") for tk in all_time_keys()]
    await db.swap_clock_style("t", [(0, "clock_t_v1_0_by_bot", 180)], emoji)

    assert [r["pack_name"] for r in await db.get_clock_packs("t")] == [
        "clock_t_v1_0_by_bot"
    ]
    assert await db.get_clock_emoji("00:00", "t") == "new-00:00"
    assert await db.count_clock_emojis("t") == 1440
    assert await db.get_clock_emoji("00:00", "other") is None  # другие стили не тронуты


# -------------------------- синхронизация с Telegram -------------------------


class FakeStickerBot:
    """Наборы в памяти. Эмодзи-id содержит слот, поэтому видно, что куда попало."""

    def __init__(self, flood_once=False, fail_set_prefix=None):
        self.sets, self.calls, self.n = {}, [], 0
        self.flood_once, self.fail_set_prefix = flood_once, fail_set_prefix
        self.session = types.SimpleNamespace(close=self._noop)

    async def _noop(self):
        return None

    def _sticker(self, sticker):
        self.n += 1
        slot = sticker.sticker.filename[:-4].replace("-", ":")
        return types.SimpleNamespace(
            file_id=f"f{self.n}", custom_emoji_id=f"id{self.n}|{slot}", slot=slot
        )

    async def _tick(self, kind, name):
        import asyncio

        await asyncio.sleep(0)  # дать пройти параллельным задачам
        self.calls.append(kind)
        if self.flood_once:
            self.flood_once = False
            raise TelegramRetryAfter(
                method=GetStickerSet(name=name), message="Flood", retry_after=0
            )
        if (
            self.fail_set_prefix
            and name.startswith(self.fail_set_prefix)
            and kind == "add"
        ):
            raise RuntimeError("telegram сломался")

    async def get_me(self):
        return types.SimpleNamespace(username="TestBot")

    async def get_sticker_set(self, name):
        await self._tick("get", name)
        if name not in self.sets:
            raise TelegramBadRequest(
                method=GetStickerSet(name=name),
                message="Bad Request: STICKERSET_INVALID",
            )
        return types.SimpleNamespace(stickers=list(self.sets[name]))

    async def create_new_sticker_set(
        self, user_id, name, title, stickers, sticker_type, needs_repainting
    ):
        assert (
            sticker_type == "custom_emoji"
            and needs_repainting is True
            and len(stickers) <= 50
        )
        await self._tick("create", name)
        self.sets[name] = [self._sticker(s) for s in stickers]

    async def add_sticker_to_set(self, user_id, name, sticker):
        await self._tick("add", name)
        self.sets[name].append(self._sticker(sticker))

    async def delete_sticker_set(self, name):
        await self._tick("delete", name)
        del self.sets[name]


def tiny_style(style_id, hours, revision=1):
    return ClockStyle(
        id=style_id,
        revision=revision,
        titles={"ru": style_id, "en": style_id, "uk": style_id},
        render=lambda slot: Image.new("RGBA", (100, 100), (0, 0, 0, 255)),
        hours=hours,
    )


async def sync(bot, styles, **kwargs):
    options = dict(delete_delay=0, retry_padding=0.0, log=lambda *_: None)
    options.update(kwargs)
    return await runner.run(bot, db, styles, **options)


async def seed_legacy(bot, style_id, count, owner="oldbot"):
    """Старые паки без ревизии в имени (как у уже работающих стилей)."""
    for i in range(count):
        name = f"clock_{style_id}{i}_by_{owner}"
        bot.sets[name] = [
            types.SimpleNamespace(
                file_id="x", custom_emoji_id=f"legacy{i}-{j}", slot=""
            )
            for j in range(180)
        ]
        await db.upsert_clock_pack(i, name, 180, True, style_id)
        await db.save_clock_emoji("00:00", i, f"legacy{i}", style_id)


async def test_sync_replaces_legacy_packs_and_deletes_old(database):
    style = tiny_style("t4", hours=4)  # 240 слотов = 2 пака (180 + 60)
    bot = FakeStickerBot()
    await seed_legacy(bot, "t4", 2)

    assert await sync(bot, [style]) is True

    new_names = {style.pack_name(i, "testbot") for i in range(2)}
    assert set(bot.sets) == new_names  # старые удалены полностью, новые на месте
    assert [len(bot.sets[n]) for n in sorted(new_names)] == [180, 60]
    # каждая минута указывает на эмодзи ИМЕННО своего слота
    for time_key in all_time_keys():
        emoji_id = await db.get_clock_emoji(time_key, "t4")
        assert emoji_id.endswith("|" + style.slot_for(time_key)), time_key
    assert await db.count_clock_emojis("t4") == 1440
    assert await db.get_clock_pack_counts() == {"t4": 2}


async def test_sync_is_idempotent_when_up_to_date(database):
    style, bot = tiny_style("t2", hours=2), FakeStickerBot()
    await sync(bot, [style])
    calls = len(bot.calls)
    assert await sync(bot, [style]) is True
    assert len(bot.calls) == calls  # ничего не трогали


async def test_changing_revision_rebuilds_and_drops_previous(database):
    bot = FakeStickerBot()
    await sync(bot, [tiny_style("t2", 2, revision=1)])
    await sync(bot, [tiny_style("t2", 2, revision=2)])
    assert set(bot.sets) == {"clock_t2_v2_0_by_testbot"}
    assert [r["pack_name"] for r in await db.get_clock_packs("t2")] == [
        "clock_t2_v2_0_by_testbot"
    ]


async def test_analog_style_shares_emoji_between_am_and_pm(database):
    style, bot = (
        tiny_style("t1", hours=1),
        FakeStickerBot(),
    )  # 60 слотов: любой час -> 00:MM
    await sync(bot, [style])
    assert await db.get_clock_emoji("05:07", "t1") == await db.get_clock_emoji(
        "17:07", "t1"
    )
    assert (await db.get_clock_emoji("05:07", "t1")).endswith("|00:07")
    assert sum(len(v) for v in bot.sets.values()) == 60  # загружено 60, а не 1440


async def test_sync_resumes_partial_pack_without_duplicates(database):
    style, bot = tiny_style("t4", hours=4), FakeStickerBot()
    name = style.pack_name(0, "testbot")
    first = [
        types.SimpleNamespace(
            sticker=types.SimpleNamespace(filename=f"{s.replace(':', '-')}.png")
        )
        for s in style.pack_slots(0)[:70]
    ]
    bot.sets[name] = [
        bot._sticker(s) for s in first
    ]  # «прерванная» загрузка: 70 из 180

    await sync(bot, [style])
    slots = [s.slot for s in bot.sets[name]]
    assert slots == list(style.pack_slots(0))  # ровно по порядку, без повторов
    assert bot.calls.count("create") == 1  # создан только второй пак


async def test_failed_style_is_not_switched_and_can_be_resumed(database):
    good, bad = tiny_style("g1", 1), tiny_style("b2", 4)
    bot = FakeStickerBot(fail_set_prefix="clock_b2")
    await seed_legacy(bot, "b2", 2)

    assert await sync(bot, [good, bad]) is False
    assert await db.get_clock_pack_counts() == {
        "b2": 2,
        "g1": 1,
    }  # g1 готов, b2 остался на старых
    assert (await db.get_clock_emoji("00:00", "b2")).startswith(
        "legacy"
    )  # БД не тронута
    assert "clock_b21_by_oldbot" in bot.sets  # старые паки не удалены

    bot.fail_set_prefix = None
    assert await sync(bot, [good, bad]) is True
    assert "clock_b21_by_oldbot" not in bot.sets
    assert (await db.get_clock_emoji("00:00", "b2")).endswith("|00:00")


async def test_flood_limit_pauses_and_recovers(database):
    style, bot = tiny_style("t2", 2), FakeStickerBot(flood_once=True)
    assert await sync(bot, [style]) is True
    assert bot.flood_once is False  # flood-limit реально случился и был пережит
    assert await db.count_clock_emojis("t2") == 1440


async def test_dry_run_and_keep_old(database):
    style, bot = tiny_style("t2", 2), FakeStickerBot()
    await seed_legacy(bot, "t2", 1)

    assert await sync(bot, [style], dry_run=True) is True
    assert bot.calls == [] and "clock_t20_by_oldbot" in bot.sets

    await sync(bot, [style], keep_old=True)
    assert "clock_t20_by_oldbot" in bot.sets  # старый комплект оставлен


def test_emoji_rows_cover_all_minutes():
    style = tiny_style("t4", 4)
    ids = [[f"p0-{i}" for i in range(180)], [f"p1-{i}" for i in range(60)]]
    rows = emoji_rows(style, ids)
    assert len(rows) == 1440 and rows[0] == ("00:00", 0, "p0-0")
    assert (
        dict((r[0], r[2]) for r in rows)["03:59"] == "p1-59"
    )  # слот 03:59 — последний


# ----------------------------------- API ------------------------------------


async def test_style_picker_api(client):
    h = client.owner
    # пока паков нет, выбирать нечего
    info = (await client.get("/api/emoji-status", headers=h)).json()
    assert info["style"] == "classic" and not any(
        s["available"] for s in info["styles"]
    )
    assert (
        await client.post(
            "/api/settings/emoji-status/style", headers=h, json={"style": "analog"}
        )
    ).status_code == 400

    analog = get_style("analog")
    for i in range(analog.pack_count):
        await db.upsert_clock_pack(i, analog.pack_name(i, "bot"), 180, True, "analog")

    info = (await client.get("/api/emoji-status", headers=h)).json()
    assert [s["id"] for s in info["styles"] if s["available"]] == [
        "analog"
    ]  # у аналоговых 4 пака хватает
    ok = await client.post(
        "/api/settings/emoji-status/style", headers=h, json={"style": "analog"}
    )
    assert ok.status_code == 200 and ok.json() == {"style": "analog"}
    assert (await client.get("/api/account", headers=h)).json()["emoji_status"][
        "style"
    ] == "analog"
    assert (
        await client.post(
            "/api/settings/emoji-status/style", headers=h, json={"style": "nope"}
        )
    ).status_code == 400
