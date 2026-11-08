"""Настройки оформления архива: вкл/выкл Rich, стиль альбома, сворачивание, карта,
история правок, расшифровка голосовых."""

import asyncio
import types

import pytest

from config import settings
from core import database as db
from core.archive_prefs import defaults, parse, validate_patch
from handlers import business_messages
from handlers.business_messages import on_business_message
from modules.archive import on_business_deleted, on_business_edited

from .conftest import CONNECTION_ID, deleted_event, make_message, tg_file
from .test_archive_snapshot import block_text, kinds, media_of, photo, texts

CHAT = 7


@pytest.fixture
async def rich(connection, api_bot, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", True)
    await db.disable_module(CONNECTION_ID, "scam")
    return connection


async def prefs(**values):
    await db.save_archive_prefs_data(CONNECTION_ID, values)


async def receive(bot, text=None, group=None, **kwargs):
    msg = make_message(text, chat_id=CHAT, from_id=CHAT, **kwargs)
    if group:
        msg.media_group_id = group
    await on_business_message(msg, bot)
    return msg


async def delete(bot, *messages):
    await on_business_deleted(
        deleted_event(CHAT, [m.message_id for m in messages]), bot
    )


async def edit(bot, msg, text=None, **kwargs):
    edited = make_message(text, chat_id=CHAT, from_id=CHAT, **kwargs)
    edited.message_id = msg.message_id
    await on_business_edited(edited, bot)


# ------------------------------- сами настройки -------------------------------


def test_defaults_follow_env_and_invalid_values_are_ignored(monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_ALBUM_STYLE", "collage")
    assert defaults().album_style == "collage"
    parsed = parse(
        {"album_style": "zzz", "rich": "yes", "unknown": 1, "location_map": True}
    )
    assert parsed.album_style == "collage" and parsed.rich is True
    assert parsed.location_map is True


def test_patch_validation():
    assert validate_patch({"rich_kinds": ["document", "photo", "photo"]}) == {
        "rich_kinds": ("photo", "document")
    }
    for bad in (
        {"album_style": "x"},
        {"rich": 1},
        {"rich_kinds": ["sticker"]},
        {"nope": True},
    ):
        with pytest.raises(ValueError):
            validate_patch(bad)


async def test_settings_api_roundtrip(connection, client):
    response = await client.get("/api/archive/settings", headers=client.owner)
    body = response.json()
    assert body["prefs"]["album_style"] == "slideshow" and body["prefs"]["rich"] is True
    assert "collage" in body["options"]["album_style"]

    saved = await client.post(
        "/api/archive/settings",
        json={"album_style": "collage", "collapse_media": True},
        headers=client.owner,
    )
    assert saved.json()["prefs"]["album_style"] == "collage"
    again = (await client.get("/api/archive/settings", headers=client.owner)).json()
    assert again["prefs"]["collapse_media"] is True and again["prefs"]["rich"] is True

    bad = await client.post(
        "/api/archive/settings", json={"album_style": "zzz"}, headers=client.owner
    )
    assert bad.status_code == 400


# --------------------------- влияние на уведомления ---------------------------


async def test_rich_can_be_switched_off_per_user(rich, bot):
    await prefs(rich=False)
    msg = await receive(bot, caption="чек", photo=photo("p"))
    await delete(bot, msg)
    assert bot.rich_sent == [] and bot.media_sent[0][0] == "photo"


async def test_rich_kinds_are_chosen_per_user(rich, bot):
    await prefs(rich_kinds=["document"])  # фото — обычным сообщением
    photo_msg = await receive(bot, photo=photo("p"))
    doc_msg = await receive(bot, document=tg_file("d", file_name="a"))
    await delete(bot, photo_msg, doc_msg)
    assert [k for k, _ in bot.media_sent] == ["photo"] and len(bot.rich_sent) == 1


@pytest.mark.parametrize(
    ("style", "container"),
    [("slideshow", "slideshow"), ("collage", "collage"), ("list", None)],
)
async def test_album_style(rich, bot, style, container):
    await prefs(album_style=style)
    msgs = [await receive(bot, photo=photo(f"p{i}"), group="g") for i in range(3)]
    await delete(bot, *msgs)
    types_ = kinds(bot.rich_sent[0]["rich_message"])
    if container:
        assert container in types_ and "photo" not in types_
    else:
        assert types_.count("photo") == 3  # просто подряд, без карусели


async def test_collapsed_media(rich, bot):
    await prefs(collapse_media=True)
    msgs = [await receive(bot, photo=photo(f"p{i}"), group="g") for i in range(2)]
    await delete(bot, *msgs)
    message = bot.rich_sent[0]["rich_message"]
    details = next(b for b in message.blocks if b.type == "details")
    assert "Вложения: 2" in texts(message) and details.is_open is False
    assert [b.type for b in details.blocks] == ["slideshow"]


async def test_edit_history_can_be_turned_off(rich, bot):
    await prefs(edit_history=False)
    msg = await receive(bot, "a")
    await edit(bot, msg, "b")
    await edit(bot, msg, "c")
    assert len(bot.rich_sent) == 2 and bot.edited == []
    assert "Изменений: 1" in texts(bot.rich_sent[1]["rich_message"])


async def test_caption_edit_can_hide_the_file(rich, bot):
    await prefs(caption_edit_media=False)
    uid = photo("p", "u1")
    msg = await receive(bot, caption="до", photo=uid)
    await edit(bot, msg, caption="после", photo=uid)
    assert "photo" not in kinds(bot.rich_sent[0]["rich_message"])


async def test_location_as_map_is_optional(rich, bot):
    def location():
        msg = make_message(chat_id=CHAT, from_id=CHAT)
        msg.location = types.SimpleNamespace(latitude=50.4, longitude=30.6)
        return msg

    off = location()
    await on_business_message(off, bot)
    await delete(bot, off)
    assert bot.rich_sent == [] and bot.media_sent[0][0] == "location"  # как раньше

    await prefs(location_map=True)
    on = location()
    await on_business_message(on, bot)
    await delete(bot, on)
    block = next(b for b in bot.rich_sent[0]["rich_message"].blocks if b.type == "map")
    assert block.location.latitude == 50.4 and block.zoom == 15


# ---------------------------- расшифровка голосовых ---------------------------


async def wait_background():
    if business_messages._background:
        await asyncio.gather(*list(business_messages._background))


@pytest.fixture
def fake_stt(monkeypatch):
    calls = []

    async def transcribe(data, locale="ru"):
        calls.append(locale)
        return "привет, это расшифровка"

    monkeypatch.setattr("core.stt.transcribe_audio", transcribe)
    return calls


async def test_voice_is_not_transcribed_by_default(rich, bot, fake_stt):
    await receive(bot, voice=tg_file("vo", duration=5))
    await wait_background()
    assert fake_stt == []


async def test_transcript_goes_into_the_regular_caption(rich, bot, fake_stt):
    await prefs(voice_transcript=True)
    msg = await receive(bot, voice=tg_file("vo", duration=5))
    await wait_background()
    assert fake_stt == ["ru"]
    await delete(bot, msg)  # голосовое по умолчанию — обычное сообщение
    caption = bot.media_sent[0][1]["caption"]
    assert "Расшифровка" in caption and "привет, это расшифровка" in caption


async def test_transcript_is_a_collapsed_block_in_rich(rich, bot, fake_stt):
    await prefs(voice_transcript=True, rich_kinds=["voice"])
    msg = await receive(bot, voice=tg_file("vo", duration=5))
    await wait_background()
    await delete(bot, msg)
    message = bot.rich_sent[0]["rich_message"]
    details = next(b for b in message.blocks if b.type == "details")
    assert "Расшифровка" in block_text(details) and "это расшифровка" in block_text(
        details
    )


async def test_long_voice_is_skipped(rich, bot, fake_stt):
    await prefs(voice_transcript=True)
    await receive(bot, voice=tg_file("vo", duration=600))
    await wait_background()
    assert fake_stt == []


async def test_failed_recognition_does_not_break_anything(rich, bot, monkeypatch):
    async def broken(data, locale="ru"):
        raise RuntimeError("no network")

    monkeypatch.setattr("core.stt.transcribe_audio", broken)
    await prefs(voice_transcript=True)
    msg = await receive(bot, voice=tg_file("vo", duration=5))
    await wait_background()
    await delete(bot, msg)
    assert "Расшифровка" not in bot.media_sent[0][1]["caption"]


async def test_transcript_is_exposed_to_the_web(rich, bot, client, fake_stt):
    await prefs(voice_transcript=True)
    msg = await receive(bot, voice=tg_file("vo", duration=5))
    await wait_background()
    await delete(bot, msg)
    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["old"]["transcript"] == "привет, это расшифровка"


# ---------------------------------- подарки -----------------------------------


async def test_gift_sticker_is_downloadable_by_the_web(rich, bot, client):
    from aiogram.types import Gift, GiftInfo, Sticker

    sticker = Sticker(
        file_id="gift-st",
        file_unique_id="u",
        type="regular",
        width=512,
        height=512,
        is_animated=True,
        is_video=False,
    )
    msg = make_message(chat_id=CHAT, from_id=CHAT)
    msg.gift = GiftInfo(gift=Gift(id="g", sticker=sticker, star_count=5))
    await on_business_message(msg, bot)
    await delete(bot, msg)

    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["old"]["kind"] == "gift" and entry["old"]["has_file"] is True
    assert entry["old"]["payload"]["sticker"]["is_animated"] is True
    media = await client.get(
        f"/api/archive/{entry['log_id']}/media", headers=client.owner
    )
    assert media.status_code == 200 and media.content == b"bytes:files/gift-st"
