"""Стикеры интерфейса: реестр, GET /api/ui-stickers/{name}, команда для id, превью часов."""

import logging
import types
from datetime import UTC, datetime

import pytest

from app.features.emoji_clock.models import ClockEmoji
from app.features.emoji_clock.queries import upsert_clock_pack
from app.features.emoji_clock.style import all_time_keys, local_time_key
from app.features.ui_stickers import api as ui_api
from app.features.ui_stickers import bot as ui_bot
from app.platform.media import MAX_CUSTOM_EMOJI_BYTES
from app.platform.ui_stickers import REGISTRY, StickerName, emoji, sticker
from config import settings

NAME = "error_forbidden"
SET = REGISTRY[NAME].set_name
UNIQUE = REGISTRY[NAME].unique_id


@pytest.fixture(autouse=True)
def clean_cache():
    ui_api._cache.clear()
    yield
    ui_api._cache.clear()


def tg_sticker(unique=UNIQUE, file_id="s1", size=2000, *, animated=False, video=False):
    return types.SimpleNamespace(
        file_id=file_id,
        file_unique_id=unique,
        file_size=size,
        is_animated=animated,
        is_video=video,
    )


async def fetch(client, name=NAME):
    return await client.get(f"/api/ui-stickers/{name}", headers=client.owner)


def test_registry_entries_are_well_formed():
    assert REGISTRY, "реестр пуст"
    for name, ref in REGISTRY.items():
        by_emoji = bool(ref.emoji_id)
        by_set = bool(ref.set_name and ref.unique_id)
        assert by_emoji != by_set, (
            f"{name}: нужен либо emoji_id, либо set_name+unique_id"
        )
        if by_emoji:
            assert ref.emoji_id.isdigit()
        else:
            assert ref.unique_id.startswith("AgAD")  # unique_id обычного стикера


def test_names_enum_follows_registry():
    assert {n.value for n in StickerName} == set(REGISTRY)


@pytest.mark.parametrize(
    ("flags", "mime"),
    [
        ({"animated": True}, "application/x-tgsticker"),
        ({"video": True}, "video/webm"),
        ({}, "image/webp"),
    ],
)
async def test_format_follows_sticker_flags(client, api_bot, flags, mime):
    api_bot.sticker_sets[SET] = [tg_sticker("other", "x"), tg_sticker(**flags)]
    response = await fetch(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == mime
    assert response.content == b"bytes:files/s1"  # взят стикер с нужным unique_id


async def test_served_from_cache(client, api_bot):
    api_bot.sticker_sets[SET] = [tg_sticker()]
    for _ in range(3):
        assert (await fetch(client)).status_code == 200
    assert api_bot.set_calls == [SET]


async def test_missing_set_is_404_and_remembered(client, api_bot):
    for _ in range(3):
        assert (await fetch(client)).status_code == 404
    assert api_bot.set_calls == [SET]


async def test_sticker_absent_from_set_is_404_and_logged_as_error(
    client, api_bot, caplog
):
    api_bot.sticker_sets[SET] = [tg_sticker("other")]
    with caplog.at_level(logging.ERROR, logger="bot.ui_stickers"):
        assert (await fetch(client)).status_code == 404
    records = [r for r in caplog.records if r.name == "bot.ui_stickers"]
    assert records and records[0].exc_info, (
        "ошибка реестра должна попасть в журнал ошибок"
    )


async def test_custom_emoji_entry_uses_emoji_endpoint(client, api_bot, monkeypatch):
    monkeypatch.setitem(REGISTRY, NAME, emoji("5368324170671202286"))
    api_bot.custom_emoji["5368324170671202286"] = tg_sticker(file_id="e1")
    response = await fetch(client)
    assert response.status_code == 200
    assert response.content == b"bytes:files/e1"
    assert api_bot.set_calls == []


async def test_oversized_file_is_not_downloaded(client, api_bot):
    api_bot.sticker_sets[SET] = [tg_sticker(size=MAX_CUSTOM_EMOJI_BYTES + 1)]
    assert (await fetch(client)).status_code == 404


async def test_unknown_name_is_rejected(client, api_bot):
    assert (await fetch(client, "nope")).status_code == 422
    assert api_bot.set_calls == []


async def test_requires_init_data(client):
    response = await client.get(f"/api/ui-stickers/{NAME}")
    assert response.status_code in (401, 422)


# ------------------------- команда «пришли стикер» ------------------------


def message(*, user=1, chat="private", sticker=None, entities=None):
    return types.SimpleNamespace(
        chat=types.SimpleNamespace(type=chat),
        from_user=types.SimpleNamespace(id=user),
        sticker=sticker,
        entities=entities,
    )


def custom_emoji_entity(emoji_id):
    return types.SimpleNamespace(type="custom_emoji", custom_emoji_id=emoji_id)


@pytest.fixture
def admin(monkeypatch):
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", "1")


def set_sticker(set_name="UtyaDuck", unique="AgADxx", custom=None):
    return types.SimpleNamespace(
        set_name=set_name, file_unique_id=unique, custom_emoji_id=custom
    )


def test_only_admin_in_private_gets_an_answer(admin):
    st = set_sticker()
    assert ui_bot._wanted(message(sticker=st))
    assert not ui_bot._wanted(message(user=2, sticker=st))
    assert not ui_bot._wanted(message(chat="group", sticker=st))
    assert not ui_bot._wanted(message())  # обычный текст без эмодзи


def test_describe_sticker_gives_registry_line():
    text = ui_bot.describe(message(sticker=set_sticker()), "en")
    assert 'sticker("UtyaDuck", "AgADxx")' in text


def test_describe_premium_emoji_in_text():
    text = ui_bot.describe(message(entities=[custom_emoji_entity("123")]), "ru")
    assert 'emoji("123")' in text


def test_describe_sticker_without_set_explains_why():
    text = ui_bot.describe(message(sticker=set_sticker(set_name=None)), "en")
    assert "not from a set" in text
    assert "sticker(" not in text


def test_helpers_build_refs():
    assert sticker("S", "AgADa").unique_id == "AgADa"
    assert emoji("7").emoji_id == "7"


# ------------------------- живое превью часов -----------------------------


async def test_clock_style_preview_follows_current_minute(client):
    h = client.owner
    # паков нет: превью нет
    info = (await client.get("/api/emoji-status", headers=h)).json()
    assert all(s["preview_emoji_id"] is None for s in info["styles"])

    await ClockEmoji.bulk_create(
        [
            ClockEmoji(style="classic", time_key=key, pack_index=0, custom_emoji_id=key)
            for key in all_time_keys()
        ]
    )
    info = (await client.get("/api/emoji-status", headers=h)).json()
    by_style = {s["id"]: s["preview_emoji_id"] for s in info["styles"]}
    assert by_style["classic"] in set(all_time_keys())  # id = минута (в тесте)
    assert by_style["analog"] is None  # у остальных стилей строк нет

    account = (await client.get("/api/account", headers=h)).json()
    assert {s["id"] for s in account["emoji_status"]["styles"]} == set(by_style)
    assert any(s["preview_emoji_id"] for s in account["emoji_status"]["styles"])


async def test_style_switch_response_has_no_preview_cost(client):
    # выбор стиля не считает превью (owner_id не передаётся): ответ прежний
    from app.features.emoji_clock import get_style

    analog = get_style("analog")
    for i in range(analog.pack_count):
        await upsert_clock_pack(i, analog.pack_name(i, "bot"), 180, True, "analog")
    response = await client.post(
        "/api/settings/emoji-status/style",
        headers=client.owner,
        json={"style": "analog"},
    )
    assert response.json() == {"style": "analog"}


def test_local_time_key_applies_offset():
    now = datetime(2026, 11, 27, 22, 30, tzinfo=UTC)
    assert local_time_key(now, 180) == "01:30"
    assert local_time_key(now, -90) == "21:00"


# ------------------------- выгрузка файлов для сборки ----------------------


async def test_export_writes_files_named_by_registry(tmp_path, api_bot):
    from scripts.export_ui_stickers import export

    api_bot.sticker_sets[SET] = [tg_sticker(animated=True)]
    result = await export(api_bot, tmp_path, [NAME])
    assert (tmp_path / f"{NAME}.tgs").read_bytes() == b"bytes:files/s1"
    assert "tgs" in result[NAME]


async def test_export_reports_failures_per_sticker(tmp_path, api_bot):
    from scripts.export_ui_stickers import export

    result = await export(api_bot, tmp_path, [NAME])  # набора нет
    assert "не отдал" in result[NAME]
    api_bot.sticker_sets[SET] = [tg_sticker("other")]
    result = await export(api_bot, tmp_path, [NAME])
    assert "нет в наборе" in result[NAME]
    assert list(tmp_path.iterdir()) == []
