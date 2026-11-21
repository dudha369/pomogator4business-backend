"""Кастомные эмодзи для веба: формат по флагам стикера, кэш, 404 вместо 500, лимит размера."""

import types

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetCustomEmojiStickers

from app.features.custom_emoji import api as emoji_api
from app.platform.media import MAX_CUSTOM_EMOJI_BYTES

EMOJI = "5368324170671202286"


@pytest.fixture(autouse=True)
def clean_cache():
    emoji_api._cache.clear()
    yield
    emoji_api._cache.clear()


def sticker(file_id="e1", size=2000, *, animated=False, video=False):
    return types.SimpleNamespace(
        file_id=file_id, file_size=size, is_animated=animated, is_video=video
    )


async def fetch(client, emoji_id=EMOJI):
    return await client.get(f"/api/custom-emoji/{emoji_id}", headers=client.owner)


@pytest.mark.parametrize(
    ("flags", "mime"),
    [
        ({"animated": True}, "application/x-tgsticker"),
        ({"video": True}, "video/webm"),
        ({}, "image/webp"),
    ],
)
async def test_format_follows_sticker_flags(client, api_bot, flags, mime):
    api_bot.custom_emoji[EMOJI] = sticker(**flags)
    response = await fetch(client)
    assert response.status_code == 200
    assert response.headers["content-type"] == mime
    assert response.content == b"bytes:files/e1"


async def test_served_from_cache(client, api_bot):
    api_bot.custom_emoji[EMOJI] = sticker()
    for _ in range(4):
        assert (await fetch(client)).status_code == 200
    assert len(api_bot.emoji_calls) == 1  # а не четыре похода в Telegram


async def test_unknown_emoji_is_404_and_remembered(client, api_bot):
    for _ in range(3):
        assert (await fetch(client)).status_code == 404
    assert len(api_bot.emoji_calls) == 1


async def test_telegram_error_is_404_not_500(client, api_bot, monkeypatch):
    async def broken(ids):
        raise TelegramBadRequest(
            method=GetCustomEmojiStickers(custom_emoji_ids=ids),
            message="Bad Request: STICKER_INVALID",
        )

    import bot_instance

    monkeypatch.setattr(bot_instance.bot, "get_custom_emoji_stickers", broken)
    assert (await fetch(client)).status_code == 404


async def test_oversized_file_is_not_downloaded(client, api_bot):
    api_bot.custom_emoji[EMOJI] = sticker(size=MAX_CUSTOM_EMOJI_BYTES + 1)
    assert (await fetch(client)).status_code == 404


@pytest.mark.parametrize("bad", ["abc", "1" * 40, "12%2F34"])
async def test_id_must_be_digits(client, api_bot, bad):
    assert (await fetch(client, bad)).status_code in (404, 422)
    assert api_bot.emoji_calls == []


async def test_requires_init_data(client):
    response = await client.get(f"/api/custom-emoji/{EMOJI}")
    assert response.status_code in (401, 422)


def test_cache_evicts_oldest_not_everything(monkeypatch):
    monkeypatch.setattr(emoji_api, "_MAX_ENTRIES", 3)
    for i in range(5):
        emoji_api._remember(str(i), (b"x", "image/webp"))
    assert list(emoji_api._cache) == ["2", "3", "4"]
