"""Спасение исчезающих медиа: владелец отвечает на сообщение, которого нет в истории."""

import types

import pytest

from config import settings
from core import database as db
from handlers.business_messages import on_business_message
from modules.archive import on_business_deleted

from .conftest import CONNECTION_ID, OWNER_ID, deleted_event, make_message, tg_file

CHAT = 7


@pytest.fixture
async def ready(connection, api_bot, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", True)
    await db.disable_module(CONNECTION_ID, "scam")
    return connection


def owner_reply(replied):
    msg = make_message("ага", chat_id=CHAT, from_id=OWNER_ID, reply_to=replied)
    return msg


async def test_owner_reply_to_unknown_message_does_not_crash(ready, bot):
    replied = make_message(chat_id=CHAT, from_id=CHAT)  # обычное сообщение без медиа
    await on_business_message(owner_reply(replied), bot)


async def test_owner_reply_to_known_message_does_not_crash(ready, bot):
    original = make_message("привет", chat_id=CHAT, from_id=CHAT)
    await on_business_message(original, bot)
    await on_business_message(owner_reply(original), bot)


async def test_self_destructing_photo_is_rescued_with_bytes(ready, bot):
    replied = make_message(
        caption="секрет", photo=[tg_file("secret")], chat_id=CHAT, from_id=CHAT
    )
    await on_business_message(owner_reply(replied), bot)

    entry = await db.get_history_entry(CONNECTION_ID, CHAT, replied.message_id)
    assert (
        entry["media_type"] == "photo" and entry["media_data"] == b"bytes:files/secret"
    )
    assert entry["kind"] == "photo" and entry["text"] == "секрет"

    # байты спасённого файла важнее file_id, поэтому Rich не используется
    await on_business_deleted(deleted_event(CHAT, [replied.message_id]), bot)
    assert bot.rich_sent == []
    ((kind, kw),) = bot.media_sent
    assert kind == "photo" and "секрет" in kw["caption"]
    assert getattr(kw["photo"], "filename", None) is not None or kw["photo"] != "secret"


async def test_rescue_skips_messages_already_in_history(ready, bot):
    original = make_message(
        caption="обычное", photo=[tg_file("p")], chat_id=CHAT, from_id=CHAT
    )
    await on_business_message(original, bot)
    await on_business_message(owner_reply(original), bot)
    entry = await db.get_history_entry(CONNECTION_ID, CHAT, original.message_id)
    assert entry["media_data"] is None and entry["file_id"] == "p"
