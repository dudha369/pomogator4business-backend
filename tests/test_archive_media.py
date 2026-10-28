"""Медиа должно переживать удаление сообщения: владелец видит его в архиве."""

import pytest

from core import database as db
from handlers.business_messages import on_business_message
from modules.archive import on_business_deleted

from .conftest import CONNECTION_ID, deleted_event, make_message, tg_file

CHAT = 7


@pytest.fixture
async def archive_ready(connection):
    await db.disable_module(CONNECTION_ID, "scam")  # без лишних уведомлений в тестах
    return connection


async def receive(bot, **kwargs):
    msg = make_message(chat_id=CHAT, from_id=CHAT, **kwargs)
    await on_business_message(msg, bot)
    return msg


async def test_photo_survives_deletion_and_is_served_by_api(archive_ready, bot, client):
    msg = await receive(
        bot, caption="Мой чек", photo=[tg_file("small"), tg_file("big")]
    )
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert (
        entry["event"] == "deleted" and entry["old_text"] == "Мой чек"
    )  # подпись — текстом
    assert entry["media_type"] == "photo" and entry["media_available"] is True

    media = await client.get(
        f"/api/archive/{entry['log_id']}/media", headers=client.owner
    )
    assert (
        media.status_code == 200 and media.content == b"bytes:files/big"
    )  # самое большое фото
    assert media.headers["content-type"] == "image/jpeg"


@pytest.mark.parametrize(
    "kind,field,mime",
    [
        ("video", tg_file("v", mime_type="video/mp4"), "video/mp4"),
        ("video_note", tg_file("vn", length=240), "video/mp4"),
        ("voice", tg_file("vo", mime_type="audio/ogg"), "audio/ogg"),
        (
            "animation",
            tg_file("an", mime_type="video/mp4", file_name="a.mp4"),
            "video/mp4",
        ),
        (
            "audio",
            tg_file("au", mime_type="audio/mpeg", file_name="song.mp3"),
            "audio/mpeg",
        ),
        (
            "document",
            tg_file("do", mime_type="application/pdf", file_name="доклад.pdf"),
            "application/pdf",
        ),
    ],
)
async def test_every_media_kind_is_saved_and_served(
    archive_ready, bot, client, kind, field, mime
):
    msg = await receive(bot, **{kind: field})
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["media_type"] == kind and entry["media_available"] is True
    media = await client.get(
        f"/api/archive/{entry['log_id']}/media", headers=client.owner
    )
    assert media.status_code == 200 and media.headers["content-type"].startswith(mime)
    # и в личку бот тоже переслал (документы фейк-бот пишет в отдельный список)
    sent_kinds = [k for k, _ in bot.media_sent] + (
        ["document"] if bot.documents else []
    )
    assert kind in sent_kinds


async def test_sticker_saved(archive_ready, bot, client):
    msg = await receive(bot, sticker=tg_file("st", is_animated=False, is_video=False))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["media_type"] == "sticker" and entry["media_available"] is True


async def test_too_large_file_is_reported_not_silently_lost(archive_ready, bot, client):
    msg = await receive(bot, video=tg_file("huge", size=50 * 1024 * 1024))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["media_type"] == "video" and entry["media_available"] is False
    assert entry["media_status"] == "too_large"
    assert (
        await client.get(f"/api/archive/{entry['log_id']}/media", headers=client.owner)
    ).status_code == 404


async def test_expired_media_keeps_type_and_says_why(archive_ready, bot, client):
    from core.retention import run_retention_once

    msg = await receive(bot, photo=[tg_file("p")])
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    await run_retention_once(now=10**10)  # через много лет
    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["media_type"] == "photo" and entry["media_available"] is False
    assert entry["media_status"] == "expired"


async def test_edited_message_media_stays_available(archive_ready, bot, client):
    """Подпись фото изменили, потом удалили: медиа должно сохраниться."""
    from modules.archive import on_business_edited

    msg = await receive(bot, caption="до", photo=[tg_file("p")])
    edited = make_message("после", chat_id=CHAT, from_id=CHAT)
    edited.message_id = msg.message_id
    await on_business_edited(edited, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    deleted = [
        e
        for e in (await client.get("/api/archive", headers=client.owner)).json()[
            "entries"
        ]
        if e["event"] == "deleted"
    ][0]
    assert deleted["media_type"] == "photo" and deleted["media_available"] is True
