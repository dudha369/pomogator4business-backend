"""Юзербот.2: правила архива по чатам, события юзербота, файлы, сводка, API, очистка."""

import asyncio
import logging

import pytest_asyncio

from app.features.archive.models import ArchiveLog
from app.features.history import rules
from app.features.history import service as history
from app.features.history.ingest import ingest
from app.features.history.models import MessageHistory
from app.features.userbot import burst, events, notices
from app.features.userbot.ub_types import UbChat, UbDialog, UbMessage
from app.features.vault import service as vault
from app.platform.sources import userbot_connection_id
from app.platform.ttl_cache import clear_all
from config import settings
from db.models.connection import Connection

from .conftest import CONNECTION_ID, NOW, OWNER_ID, TEST_MASTER_KEYS, init_data_headers

UB = userbot_connection_id(OWNER_ID)
GROUP = -4242  # обычная группа: удаления приходят без chat_id
SUPER = -1001234567890  # супергруппа


@pytest_asyncio.fixture
async def env(database, bot, monkeypatch):
    """Шифрование включено, уведомления юзербота уходят в FakeBot, окно сводки — 0 с."""
    vault.configure(TEST_MASTER_KEYS)
    monkeypatch.setattr(notices, "_bot", lambda: bot)
    monkeypatch.setattr(settings, "USERBOT_BURST_WINDOW", 0)
    monkeypatch.setattr(settings, "USERBOT_BURST_THRESHOLD", 5)
    monkeypatch.setattr(settings, "WEBAPP_URL", "https://app.example")
    return bot


def message(
    mid, text="привет", *, chat=None, out=False, kind="text", download=None, size=None
):
    chat = chat or UbChat(GROUP, "group", "Семья", None)
    snap = {"kind": kind, "text": text, "entities": None, "file_size": size}
    return UbMessage(
        chat=chat,
        message_id=mid,
        ts=NOW,
        is_out=out,
        snapshot=snap,
        sender_id=OWNER_ID if out else 77,
        sender_name="Аня",
        sender_username=None,
        download=download,
    )


async def enable(chat_id=GROUP, kind="group", **kw):
    await rules.set_rule(OWNER_ID, chat_id, kind, enabled=True, **kw)


# --- правила ------------------------------------------------------------------------


def test_default_rules_by_kind_and_source():
    assert rules.default_rule("private", "bot").enabled
    assert not rules.default_rule("private", "userbot").enabled
    assert not rules.default_rule("group", "userbot").enabled
    assert not rules.default_rule("channel", "userbot").enabled
    assert rules.kind_of_chat(5) == "private"
    assert rules.kind_of_chat(-5) == "group"
    assert rules.kind_of_chat(SUPER) == "supergroup"


async def test_set_rule_keeps_defaults_of_other_fields(database):
    # первое касание личного чата («уведомлять») не должно его выключить
    await rules.set_rule(OWNER_ID, 5, "private", notify=False)
    rule = await rules.rule_for(OWNER_ID, 5, "private", "bot")
    assert rule == rules.Rule(enabled=True, media=False, notify=False)
    await rules.set_rule(OWNER_ID, 5, "private", enabled=False)
    assert not await rules.should_archive(OWNER_ID, 5, "private", "bot")


async def test_ingest_business_respects_disabled_private_chat(database, connection):
    kw = {
        "source": "bot",
        "connection_id": CONNECTION_ID,
        "chat_id": 555,
        "is_owner": False,
        "text": "x",
        "ts": NOW,
        "snapshot": {"kind": "text", "text": "x", "entities": None},
    }
    assert await ingest(message_id=1, **kw)  # по умолчанию личные чаты включены
    await rules.set_rule(OWNER_ID, 555, "private", enabled=False)
    assert not await ingest(message_id=2, **kw)
    assert await MessageHistory.filter(chat_id=555).count() == 1


async def test_userbot_private_chat_skipped_while_business_covers(env, connection):
    await rules.set_rule(OWNER_ID, 5, "private", enabled=True)
    msg = message(1, chat=UbChat(5, "private", "Боб"))
    await events.handle_new(OWNER_ID, msg)
    assert await MessageHistory.all().count() == 0  # приоритет у бизнес-бота


# --- новые сообщения ----------------------------------------------------------------


async def test_new_message_in_disabled_group_is_not_written(env):
    await events.handle_new(OWNER_ID, message(1))
    assert await MessageHistory.all().count() == 0


async def test_new_message_stores_chat_and_author_encrypted(env):
    await enable()
    await events.handle_new(OWNER_ID, message(1, "секрет"))
    raw = await MessageHistory.get(connection_id=UB, message_id=1)
    assert raw.enc_ver is not None and raw.text != "секрет"
    entry = await history.get_history_entry(UB, GROUP, 1)
    assert entry["text"] == "секрет"
    assert entry["raw_json"]["chat"]["title"] == "Семья"
    assert entry["raw_json"]["from"]["name"] == "Аня"


async def test_scrub_raw_json_leaves_userbot_rows(env):
    await enable()
    await events.handle_new(OWNER_ID, message(1))
    await history.scrub_raw_json(100)
    entry = await history.get_history_entry(UB, GROUP, 1)
    assert entry["raw_json"] is not None


# --- файлы ----------------------------------------------------------------------------


def file_message(mid, data, size=None):
    async def download():
        return data

    return message(
        mid, "", kind="photo", download=download, size=size or len(data or b"")
    )


async def settle():
    while events._inflight:
        await asyncio.gather(*list(events._inflight.values()), return_exceptions=True)


async def test_media_saved_when_enabled(env):
    await enable(media_enabled=True)
    await events.handle_new(OWNER_ID, file_message(1, b"PNG-bytes"))
    await settle()
    entry = await history.get_history_entry(UB, GROUP, 1)
    assert (
        entry["media_status"] == "saved" and bytes(entry["media_data"]) == b"PNG-bytes"
    )


async def test_media_not_downloaded_when_off_or_too_big(env, monkeypatch):
    called = []

    async def download():
        called.append(1)
        return b"x"

    await enable()  # файлы выключены
    msg = file_message(1, b"x")
    msg.download = download
    await events.handle_new(OWNER_ID, msg)
    assert called == []
    assert (await history.get_history_entry(UB, GROUP, 1))["media_status"] == "disabled"

    monkeypatch.setattr(settings, "USERBOT_MEDIA_MAX_BYTES", 10)
    await rules.set_rule(OWNER_ID, GROUP, "group", media_enabled=True)
    big = file_message(2, b"x" * 50)
    big.download = download
    await events.handle_new(OWNER_ID, big)
    assert called == []
    assert (await history.get_history_entry(UB, GROUP, 2))[
        "media_status"
    ] == "too_large"


async def test_media_download_failure_marks_failed(env):
    await enable(media_enabled=True)

    async def broken():
        raise RuntimeError("boom")

    msg = file_message(1, b"x")
    msg.download = broken
    await events.handle_new(OWNER_ID, msg)
    await settle()
    assert (await history.get_history_entry(UB, GROUP, 1))["media_status"] == "failed"


async def test_deletion_waits_for_pending_download(env):
    await enable(media_enabled=True)
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return b"late-bytes"

    msg = file_message(1, b"x")
    msg.download = slow
    await events.handle_new(OWNER_ID, msg)
    asyncio.get_running_loop().call_later(0.05, gate.set)
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    log = await ArchiveLog.get(connection_id=UB, message_id=1)
    assert log.media_data is not None  # файл дошёл до архива, а не потерялся


async def test_attach_media_does_not_resurrect_deleted_row(env):
    assert not await history.attach_media(UB, GROUP, 99, b"x", "saved")
    assert await MessageHistory.all().count() == 0


# --- удаления -------------------------------------------------------------------------


async def test_delete_without_chat_id_finds_by_number_among_non_channels(env, bot):
    await enable()
    await enable(SUPER, "supergroup")
    await events.handle_new(OWNER_ID, message(10, "в группе"))
    other = UbChat(SUPER, "supergroup", "Канал-чат")
    await events.handle_new(OWNER_ID, message(10, "в супергруппе", chat=other))
    await events.handle_deleted(OWNER_ID, None, [10])  # chat_id нет
    await burst.drain()
    logs = await ArchiveLog.filter(connection_id=UB, event="deleted")
    assert [log.chat_id for log in logs] == [
        GROUP
    ]  # супергруппу с тем же номером не тронули
    assert await MessageHistory.filter(chat_id=SUPER).count() == 1
    assert len(bot.sent) + len(bot.rich_sent) == 1


async def test_delete_with_chat_id_is_exact(env):
    await enable(SUPER, "supergroup")
    chat = UbChat(SUPER, "supergroup", "Чат")
    await events.handle_new(OWNER_ID, message(3, "x", chat=chat))
    await events.handle_deleted(OWNER_ID, SUPER, [3])
    await burst.drain()
    assert await ArchiveLog.filter(chat_id=SUPER, message_id=3).count() == 1


async def test_delete_diagnostics_has_no_content(env, caplog):
    await enable()
    await events.handle_new(OWNER_ID, message(1, "ОЧЕНЬ ЛИЧНОЕ"))
    with caplog.at_level(logging.INFO, logger="bot.userbot.events"):
        await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    assert "chat_id=нет" in caplog.text and "найдено в истории=1" in caplog.text
    assert "ЛИЧНОЕ" not in caplog.text


async def test_own_deletion_is_recorded_silently(env, bot):
    await enable()
    await events.handle_new(OWNER_ID, message(1, "моё", out=True))
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    log = await ArchiveLog.get(connection_id=UB, message_id=1)
    assert log.is_owner and not bot.sent and not bot.rich_sent


async def test_chat_with_notify_off_archives_without_notice(env, bot):
    await enable(notify=False)
    await events.handle_new(OWNER_ID, message(1))
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    assert await ArchiveLog.filter(connection_id=UB).count() == 1
    assert not bot.sent and not bot.rich_sent


async def test_deletion_in_disabled_chat_does_nothing(env, bot):
    await enable()
    await events.handle_new(OWNER_ID, message(1))
    await rules.set_rule(OWNER_ID, GROUP, "group", enabled=False)
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    assert await ArchiveLog.all().count() == 0 and not bot.sent


# --- сводка массового удаления --------------------------------------------------------


async def delete_many(count):
    await enable()
    for i in range(1, count + 1):
        await events.handle_new(OWNER_ID, message(i, f"m{i}"))
    await events.handle_deleted(OWNER_ID, None, list(range(1, count + 1)))
    await burst.drain()


async def test_few_deletions_come_as_separate_notices(env, bot):
    await delete_many(3)
    assert len(bot.sent) + len(bot.rich_sent) == 3


async def test_mass_deletion_is_one_summary_with_exact_count(env, bot):
    await delete_many(12)
    assert await ArchiveLog.filter(event="deleted").count() == 12  # всё записано
    assert len(bot.rich_sent) == 0 and len(bot.sent) == 1
    sent = bot.sent[0]
    assert "<b>12</b>" in sent["text"] and "Семья" in sent["text"]
    url = sent["reply_markup"].inline_keyboard[0][0].web_app.url
    assert url.startswith("https://app.example/archive?chat_id=-4242&date_from=")
    assert "&date_to=" in url


async def test_burst_batches_are_per_chat(env, bot):
    await enable()
    await enable(SUPER, "supergroup")
    other = UbChat(SUPER, "supergroup", "Другой")
    for i in range(1, 4):
        await events.handle_new(OWNER_ID, message(i, "a"))
        await events.handle_new(OWNER_ID, message(i, "b", chat=other))
    await events.handle_deleted(OWNER_ID, SUPER, [1, 2, 3])
    await events.handle_deleted(OWNER_ID, None, [1, 2, 3])
    await burst.drain()
    assert len(bot.sent) + len(bot.rich_sent) == 6  # у каждого чата своя пачка


# --- правки ---------------------------------------------------------------------------


async def test_edit_sends_notice_and_logs(env, bot):
    await enable()
    await events.handle_new(OWNER_ID, message(1, "было"))
    await events.handle_edited(OWNER_ID, message(1, "стало"))
    assert len(bot.sent) + len(bot.rich_sent) == 1
    log = await ArchiveLog.get(connection_id=UB, event="edited")
    assert vault and log.chat_id == GROUP
    entry = await history.get_history_entry(UB, GROUP, 1)
    assert entry["text"] == "стало"


async def test_edit_with_notify_off_logs_silently(env, bot):
    await enable(notify=False)
    await events.handle_new(OWNER_ID, message(1, "было"))
    await events.handle_edited(OWNER_ID, message(1, "стало"))
    assert await ArchiveLog.filter(event="edited").count() == 1
    assert not bot.sent and not bot.rich_sent


async def test_own_edit_not_announced_by_default(env, bot):
    await enable()
    await events.handle_new(OWNER_ID, message(1, "было", out=True))
    await events.handle_edited(OWNER_ID, message(1, "стало", out=True))
    assert not bot.sent and not bot.rich_sent


async def test_edit_keeps_saved_media_status(env):
    await enable(media_enabled=True)
    await events.handle_new(OWNER_ID, file_message(1, b"bytes"))
    await settle()
    await events.handle_edited(OWNER_ID, file_message(1, b"bytes"))
    entry = await history.get_history_entry(UB, GROUP, 1)
    assert entry["media_status"] == "saved" and entry["media_data"]


# --- API ------------------------------------------------------------------------------


async def test_archive_api_for_userbot_only_owner(client, env):
    await enable()
    await events.handle_new(OWNER_ID, message(1, "текст"))
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    body = (await client.get("/api/archive", headers=client.owner)).json()
    assert len(body["entries"]) == 1  # бизнес-подключения нет, архив всё равно открыт
    entry = body["entries"][0]
    assert entry["source"] == "userbot" and entry["chat_title"] == "Семья"
    assert entry["chat_kind"] == "group" and entry["sender_name"] == "Аня"
    flt = (
        await client.get(f"/api/archive?chat_id={GROUP}", headers=client.owner)
    ).json()
    assert len(flt["entries"]) == 1
    none = (await client.get("/api/archive?chat_id=1", headers=client.owner)).json()
    assert none["entries"] == []


async def test_archive_api_serves_userbot_media(client, env):
    await enable(media_enabled=True)
    await events.handle_new(OWNER_ID, file_message(1, b"PICTURE"))
    await settle()
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    entry = (await client.get("/api/archive", headers=client.owner)).json()["entries"][
        0
    ]
    assert entry["media_available"] is True
    res = await client.get(
        f"/api/archive/{entry['log_id']}/media", headers=client.owner
    )
    assert res.status_code == 200 and res.content == b"PICTURE"


async def test_archive_api_other_owner_sees_nothing(client, env):
    await enable()
    await events.handle_new(OWNER_ID, message(1))
    await events.handle_deleted(OWNER_ID, None, [1])
    await burst.drain()
    other = init_data_headers(999)
    assert (await client.get("/api/archive", headers=other)).json()["entries"] == []
    log_id = (await ArchiveLog.first()).log_id
    res = await client.get(f"/api/archive/{log_id}/media", headers=other)
    assert res.status_code == 404


async def test_rules_api_limit_on_groups_not_on_private(client, env):
    headers = client.owner
    for i in range(3):  # free: 3 группы или канала
        res = await client.put(
            f"/api/archive/rules/{-1000 - i}",
            json={"kind": "group", "enabled": True},
            headers=headers,
        )
        assert res.status_code == 200
    assert res.json()["groups_used"] == 3 and res.json()["groups_limit"] == 3
    res = await client.put(
        "/api/archive/rules/-2000",
        json={"kind": "channel", "enabled": True},
        headers=headers,
    )
    assert res.status_code == 403 and res.json()["detail"] == "limit_reached"
    # уже включённую правят свободно, личные чаты не считаются
    res = await client.put(
        "/api/archive/rules/-1000",
        json={"kind": "group", "media_enabled": True},
        headers=headers,
    )
    assert res.status_code == 200
    res = await client.put(
        "/api/archive/rules/55",
        json={"kind": "private", "enabled": True},
        headers=headers,
    )
    assert res.status_code == 200
    got = (await client.get("/api/archive/rules", headers=headers)).json()
    assert {r["chat_id"] for r in got["rules"]} == {-1000, -1001, -1002, 55}


async def test_rules_api_validates_kind(client, env):
    res = await client.put(
        "/api/archive/rules/5",
        json={"kind": "bogus", "enabled": True},
        headers=client.owner,
    )
    assert res.status_code == 422


async def test_dialogs_api(client, env, monkeypatch):
    from app.features.userbot import api as ub_api

    items = [
        UbDialog(-1, "group", "Семья"),
        UbDialog(-1001, "channel", "Новости", "news", 1000),
        UbDialog(5, "private", "Боб"),
        UbDialog(6, "private", "Бот", is_bot=True),
    ]

    async def fake(owner_id):
        return items

    monkeypatch.setattr(ub_api.manager, "dialogs", fake)
    body = (await client.get("/api/userbot/dialogs", headers=client.owner)).json()
    # бот скрыт; личные чаты тоже: у владельца подключён бизнес-бот
    assert [d["title"] for d in body["dialogs"]] == ["Семья", "Новости"]
    found = (
        await client.get("/api/userbot/dialogs?q=нов", headers=client.owner)
    ).json()
    assert [d["id"] for d in found["dialogs"]] == [-1001]
    kind = (
        await client.get("/api/userbot/dialogs?kind=group", headers=client.owner)
    ).json()
    assert len(kind["dialogs"]) == 1
    page = (
        await client.get("/api/userbot/dialogs?limit=1", headers=client.owner)
    ).json()
    assert page["has_more"] is True
    await Connection.filter(connection_id=CONNECTION_ID).update(is_enabled=False)
    clear_all()
    free = (await client.get("/api/userbot/dialogs", headers=client.owner)).json()
    assert "Боб" in [
        d["title"] for d in free["dialogs"]
    ]  # бизнес-бота нет — личные видны


async def test_dialogs_api_unavailable_without_client(client, env, monkeypatch):
    from app.features.userbot import api as ub_api

    async def none(owner_id):
        return None

    monkeypatch.setattr(ub_api.manager, "dialogs", none)
    res = await client.get("/api/userbot/dialogs", headers=client.owner)
    assert res.status_code == 503


# --- очистка окна слежения ------------------------------------------------------------


async def test_trim_history_keeps_latest_per_connection(database):
    for i in range(1, 6):
        await history.save_history(UB, GROUP, i, False, "t", NOW)
        await history.save_history("other", GROUP, i, False, "t", NOW)
    removed = await history.trim_history(2)
    assert removed == 6
    left = await MessageHistory.filter(connection_id=UB).values_list(
        "message_id", flat=True
    )
    assert sorted(left) == [4, 5]  # самые свежие остались


async def test_trim_history_media_frees_oldest_files(database):
    for i in range(1, 4):
        await history.save_history(
            UB,
            GROUP,
            i,
            False,
            None,
            NOW,
            media_type="photo",
            media_data=b"x" * 10,
            snapshot={"kind": "photo", "file_size": 10},
        )
    freed = await history.trim_history_media(max_bytes=20)
    assert freed == 1
    first = await MessageHistory.get(message_id=1)
    assert first.media_data is None and first.media_status == "trimmed"
    assert (await MessageHistory.get(message_id=3)).media_data is not None


async def test_trim_tasks_are_registered_and_off_by_zero(database, monkeypatch):
    from app.platform import retention

    names = retention.registered_tasks()
    assert "history_trimmed" in names and "history_media_trimmed" in names
    stats = await retention.run_retention_once()
    assert stats["history_trimmed"] == 0 and stats["history_media_trimmed"] == 0
    monkeypatch.setattr(settings, "HISTORY_MAX_PER_CONNECTION", 0)
    monkeypatch.setattr(settings, "HISTORY_MEDIA_MAX_MB", 0)
    stats = await retention.run_retention_once()
    assert "history_trimmed" not in stats  # 0 = выключено
