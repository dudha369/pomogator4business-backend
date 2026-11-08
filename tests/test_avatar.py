"""Аватарки собеседников: недоступный пользователь — 404, а не 500; кэш."""

import types

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import GetUserProfilePhotos

from api import avatar as avatar_api
from core import database as db

from .conftest import OWNER_ID

KNOWN = 555


@pytest.fixture(autouse=True)
def clean_cache():
    cache = getattr(avatar_api, "_cache", {})
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
async def known_chat(connection, api_bot):
    await db.mark_known_chat(OWNER_ID, KNOWN)


def bot_calls(bot, monkeypatch, handler):
    calls = []

    async def fake(user_id, limit=1):
        calls.append(user_id)
        return await handler(user_id)

    import bot_instance

    monkeypatch.setattr(
        bot_instance.bot, "get_user_profile_photos", fake, raising=False
    )
    return calls


async def test_unknown_telegram_user_is_404_not_500(
    client, known_chat, bot, monkeypatch
):
    async def missing(user_id):
        raise TelegramBadRequest(
            method=GetUserProfilePhotos(user_id=user_id),
            message="Bad Request: user not found",
        )

    bot_calls(bot, monkeypatch, missing)
    response = await client.get(f"/api/avatar/{KNOWN}", headers=client.owner)
    assert response.status_code == 404


async def test_missing_avatar_is_remembered(client, known_chat, bot, monkeypatch):
    async def none(user_id):
        return types.SimpleNamespace(photos=[])

    calls = bot_calls(bot, monkeypatch, none)
    for _ in range(5):
        assert (
            await client.get(f"/api/avatar/{KNOWN}", headers=client.owner)
        ).status_code == 404
    assert len(calls) == 1  # а не пять походов в Telegram


async def test_avatar_is_served_and_cached(client, known_chat, bot, monkeypatch):
    async def photos(user_id):
        return types.SimpleNamespace(photos=[[types.SimpleNamespace(file_id="av")]])

    calls = bot_calls(bot, monkeypatch, photos)
    first = await client.get(f"/api/avatar/{KNOWN}", headers=client.owner)
    second = await client.get(f"/api/avatar/{KNOWN}", headers=client.owner)
    assert first.status_code == second.status_code == 200
    assert first.content == b"bytes:files/av" and len(calls) == 1


async def test_stranger_is_still_forbidden(client, known_chat):
    assert (
        await client.get("/api/avatar/999", headers=client.owner)
    ).status_code == 404
