"""Шифрование содержимого в БД (HANDOFF_crypto1): шифротекст в таблицах, чтение старых и
новых строк вместе, бэкфилл, ротации, правила старта и сквозные сценарии."""

import asyncio
import json
import re

import pytest

from app.features.ai.models import AiDraft
from app.features.ai.queries import create_draft, get_draft
from app.features.alerts import service as alerts
from app.features.alerts.models import Alert
from app.features.archive.bot.deleted import on_business_deleted
from app.features.archive.bot.edited import on_business_edited
from app.features.archive.models import ArchiveLog
from app.features.archive.queries import (
    get_archive_page,
    get_edit_history,
    get_log_media,
    log_archive_event,
)
from app.features.history.models import MessageHistory
from app.features.history.service import (
    get_history_entry,
    get_history_media,
    get_history_text,
    list_chat_history,
    save_history,
    set_history_transcript,
)
from app.features.scheduled.models import ScheduledTask
from app.features.scheduled.queries import add_scheduled_task, list_due_scheduled_tasks
from app.features.vault import backfill as vb
from app.features.vault import service as vault
from app.features.vault.models import OwnerKey
from app.features.vault.retention import encrypt_old_rows, rewrap
from app.platform.crypto import (
    CryptoError,
    aead_open,
    aead_seal,
    new_key,
    parse_master_keys,
)
from config import settings
from db.models.module_settings import disable_module

from .conftest import (
    CONNECTION_ID,
    NOW,
    OWNER_ID,
    TEST_MASTER_KEYS,
    deleted_event,
    make_message,
    on_business_message,
)

K1 = TEST_MASTER_KEYS
K2 = "2:" + "B" * 43
SECRET = "секретный текст про пароль"
CHAT = 7


@pytest.fixture
async def ready(connection, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", False)
    await disable_module(CONNECTION_ID, "scam")
    vault.configure(K1)
    return connection


def snap(**extra):
    return {
        "kind": "text",
        "entities": [{"type": "bold", "offset": 0, "length": 3}],
        "payload": {"secret": SECRET},
        "forward": {"name": "Иван"},
        "raw_json": {"text": SECRET},
        "file_id": "FID",
        **extra,
    }


async def raw_history(message_id):
    return await MessageHistory.get(
        connection_id=CONNECTION_ID, chat_id=CHAT, message_id=message_id
    )


def contains_secret(*values):
    return any(
        SECRET in json.dumps(v, default=repr, ensure_ascii=False) for v in values
    )


# ------------------------------ примитивы ---------------------------------------------


def test_aead_roundtrip_and_aad_binding():
    key = new_key()
    blob = aead_seal(key, b"a", b"hello")
    assert aead_open(key, b"a", blob) == b"hello"
    with pytest.raises(CryptoError):
        aead_open(key, b"b", blob)  # другой AAD (колонка/владелец)
    with pytest.raises(CryptoError):
        aead_open(new_key(), b"a", blob)  # другой ключ
    assert aead_seal(key, b"a", b"hello") != blob  # nonce случайный


def test_master_keys_parsing():
    assert list(parse_master_keys(f"{K2},{K1}")) == [2, 1]
    assert parse_master_keys("") == {}
    for bad in ("1:short", "x:" + "A" * 43, f"{K1},{K1}", "0:" + "A" * 43, "noversion"):
        with pytest.raises(CryptoError):
            parse_master_keys(bad)


# ------------------------------ шифротекст в БД ---------------------------------------


async def test_history_content_is_ciphertext_and_metadata_is_open(ready):
    await save_history(
        CONNECTION_ID,
        CHAT,
        1,
        False,
        SECRET,
        NOW,
        media_type="photo",
        media_data=b"JPEGBYTES",
        media_mime="image/jpeg",
        media_name="паспорт.jpg",
        snapshot=snap(kind="photo"),
    )
    row = await raw_history(1)
    assert row.enc_ver == 1
    assert row.text != SECRET and "паспорт" not in row.media_name
    assert row.media_data != b"JPEGBYTES" and b"JPEGBYTES" not in row.media_data
    assert not contains_secret(row.text, row.entities, row.payload, row.raw_json)
    assert "Иван" not in json.dumps(row.forward)
    # метаданные остаются открытыми
    assert (row.kind, row.chat_id, row.is_owner, row.file_id, row.created_at) == (
        "photo",
        CHAT,
        False,
        "FID",
        NOW,
    )
    entry = await get_history_entry(CONNECTION_ID, CHAT, 1)
    assert entry["text"] == SECRET and entry["media_name"] == "паспорт.jpg"
    assert entry["entities"] == snap()["entities"] and entry["forward"] == {
        "name": "Иван"
    }
    assert entry["raw_json"] == {"text": SECRET} and "enc_ver" not in entry
    assert (await get_history_media(CONNECTION_ID, CHAT, 1))[
        "media_data"
    ] == b"JPEGBYTES"
    assert await get_history_text(CONNECTION_ID, CHAT, 1) == SECRET
    assert [m["text"] for m in await list_chat_history(CONNECTION_ID, CHAT, 5)] == [
        SECRET
    ]


async def test_archive_log_content_is_ciphertext(ready):
    log_id = await log_archive_event(
        CONNECTION_ID,
        CHAT,
        5,
        "edited",
        SECRET,
        "новый " + SECRET,
        NOW,
        media_type="photo",
        media_data=b"PNGBYTES",
        media_name="скан.png",
        old_snapshot=snap(),
        new_snapshot=snap(),
    )
    row = await ArchiveLog.get(log_id=log_id)
    assert row.enc_ver == 1 and row.media_data != b"PNGBYTES"
    assert not contains_secret(
        row.old_text, row.new_text, row.old_snapshot, row.new_snapshot
    )
    assert (row.event, row.chat_id, row.media_type) == ("edited", CHAT, "photo")
    page, _ = await get_archive_page(CONNECTION_ID, None, 10)
    assert (
        page[0]["old_text"] == SECRET
        and page[0]["old_snapshot"]["forward"]["name"] == "Иван"
    )
    media = await get_log_media(CONNECTION_ID, log_id)
    assert media["media_data"] == b"PNGBYTES" and media["media_name"] == "скан.png"
    (edit,) = await get_edit_history(CONNECTION_ID, CHAT, 5)
    assert edit["new_text"] == "новый " + SECRET


async def test_ai_drafts_alerts_and_scheduled_are_ciphertext(ready):
    draft_id = await create_draft(OWNER_ID, CHAT, 1, SECRET, NOW)
    assert (await AiDraft.get(id=draft_id)).text != SECRET
    assert (await get_draft(draft_id))["text"] == SECRET

    await alerts.record(
        OWNER_ID, "dangerous_link:evil", {"url": "https://x/?token=SECRET"}
    )
    stored = await Alert.get(owner_id=OWNER_ID)
    assert "SECRET" not in json.dumps(stored.details) and stored.enc_ver == 1
    assert (
        (await alerts.get_alert(OWNER_ID, stored.id)).details["url"].endswith("SECRET")
    )

    await add_scheduled_task("timer", CONNECTION_ID, CHAT, NOW - 1, text=SECRET)
    assert (await ScheduledTask.first()).text != SECRET
    (task,) = await list_due_scheduled_tasks(NOW)
    assert task["text"] == SECRET and "enc_ver" not in task


# ------------------------------ старые и новые строки вместе --------------------------


async def test_legacy_and_encrypted_rows_are_read_together(ready):
    vault.configure("")  # запись «до шифрования»
    await save_history(CONNECTION_ID, CHAT, 1, False, "старое", NOW, snapshot=snap())
    await log_archive_event(CONNECTION_ID, CHAT, 1, "deleted", "старое", None, NOW)
    assert (await raw_history(1)).enc_ver is None
    vault.configure(K1)
    await save_history(CONNECTION_ID, CHAT, 2, False, "новое", NOW)
    await log_archive_event(CONNECTION_ID, CHAT, 2, "deleted", "новое", None, NOW)

    assert (await raw_history(1)).text == "старое"  # открытая строка читается как есть
    assert (await get_history_entry(CONNECTION_ID, CHAT, 1))["text"] == "старое"
    assert (await get_history_entry(CONNECTION_ID, CHAT, 2))["text"] == "новое"
    page, _ = await get_archive_page(CONNECTION_ID, None, 10)
    assert sorted(e["old_text"] for e in page) == ["новое", "старое"]


async def test_editing_legacy_row_seals_the_whole_row(ready):
    vault.configure("")
    await save_history(
        CONNECTION_ID, CHAT, 1, False, "до", NOW, media_name="a.txt", snapshot=snap()
    )
    vault.configure(K1)
    await save_history(
        CONNECTION_ID, CHAT, 1, False, "после", NOW, snapshot={"kind": "text"}
    )
    row = await raw_history(1)
    assert row.enc_ver == 1 and row.text != "после"
    assert row.payload != {"secret": SECRET} and not contains_secret(
        row.payload, row.raw_json
    )
    entry = await get_history_entry(CONNECTION_ID, CHAT, 1)
    assert entry["text"] == "после" and entry["payload"] == {"secret": SECRET}


async def test_transcript_update_on_legacy_and_sealed_rows(ready):
    vault.configure("")
    await save_history(
        CONNECTION_ID, CHAT, 1, False, "голос", NOW, snapshot=snap(kind="voice")
    )
    vault.configure(K1)
    await save_history(
        CONNECTION_ID, CHAT, 2, False, "голос", NOW, snapshot=snap(kind="voice")
    )
    for message_id in (1, 2):
        await set_history_transcript(CONNECTION_ID, CHAT, message_id, SECRET)
        row = await raw_history(message_id)
        assert row.enc_ver == 1 and row.transcript != SECRET
        assert (await get_history_entry(CONNECTION_ID, CHAT, message_id))[
            "transcript"
        ] == SECRET


# ------------------------------ бэкфилл ----------------------------------------------


async def seed_legacy():
    vault.configure("")
    for i in range(1, 6):
        await save_history(
            CONNECTION_ID, CHAT, i, False, f"{SECRET} {i}", NOW, snapshot=snap()
        )
        await log_archive_event(
            CONNECTION_ID, CHAT, i, "deleted", f"{SECRET} {i}", None, NOW
        )
    await create_draft(OWNER_ID, CHAT, 1, SECRET, NOW)
    await alerts.record(OWNER_ID, "dangerous_link:e", {"url": "u"})
    await add_scheduled_task("timer", CONNECTION_ID, CHAT, NOW + 99, text=SECRET)


async def test_backfill_encrypts_everything_and_is_idempotent(ready):
    await seed_legacy()
    vault.configure(K1)
    first = await vb.backfill(3)  # потолок на таблицу: по 3 строки
    assert first == 3 + 3 + 1 + 1 + 1
    assert await encrypt_old_rows(NOW) == 2 + 2  # остальное добирает следующий проход
    for model in (MessageHistory, ArchiveLog, AiDraft, Alert, ScheduledTask):
        assert not await model.filter(enc_ver__isnull=True).exists()
    assert await vb.backfill(1000) == 0
    page, _ = await get_archive_page(CONNECTION_ID, None, 10)
    assert {e["old_text"] for e in page} == {f"{SECRET} {i}" for i in range(1, 6)}
    assert (await get_history_entry(CONNECTION_ID, CHAT, 3))["payload"] == {
        "secret": SECRET
    }
    assert not contains_secret(
        (await raw_history(3)).text, (await raw_history(3)).payload
    )


async def test_backfill_does_not_overwrite_a_row_written_meanwhile(ready):
    await seed_legacy()
    vault.configure(K1)
    await save_history(CONNECTION_ID, CHAT, 1, False, "обновлено", NOW, snapshot=snap())
    assert not await vb.reseal_row("message_history", (await raw_history(1)).id)
    assert (await get_history_entry(CONNECTION_ID, CHAT, 1))["text"] == "обновлено"


# ------------------------------ ротации -----------------------------------------------


async def test_master_key_rotation_rewraps_without_touching_data(ready):
    await save_history(CONNECTION_ID, CHAT, 1, False, SECRET, NOW)
    before = (await raw_history(1)).text
    vault.configure(f"{K2},{K1}")  # новый — первым
    assert await rewrap(NOW) == 1
    assert (await OwnerKey.get(owner_id=OWNER_ID)).master_version == 2
    assert (await raw_history(1)).text == before  # данные те же
    vault.configure(K2.split(",")[0])  # старый ключ убрали
    assert await get_history_text(CONNECTION_ID, CHAT, 1) == SECRET
    await vault.startup_check_with(K2)  # старт без старого ключа проходит


async def test_owner_key_rotation_reencrypts_rows(ready):
    await save_history(CONNECTION_ID, CHAT, 1, False, SECRET, NOW)
    assert await vault.rotate_owner_key(OWNER_ID) == 2
    await save_history(CONNECTION_ID, CHAT, 2, False, SECRET, NOW)
    assert (await raw_history(1)).enc_ver == 1 and (await raw_history(2)).enc_ver == 2
    assert (
        await get_history_text(CONNECTION_ID, CHAT, 1) == SECRET
    )  # старая версия читается
    assert await vb.reencrypt_owner(OWNER_ID) == 1
    assert (await raw_history(1)).enc_ver == 2
    assert await get_history_text(CONNECTION_ID, CHAT, 1) == SECRET


# ------------------------------ правила старта ----------------------------------------


async def test_startup_rules(ready, monkeypatch):
    await save_history(CONNECTION_ID, CHAT, 1, False, SECRET, NOW)
    with pytest.raises(vault.VaultError):  # шифротекст есть, ключей нет
        await vault.startup_check_with("")
    with pytest.raises(vault.VaultError):  # неверный ключ
        await vault.startup_check_with("1:" + "C" * 43)
    with pytest.raises(vault.VaultError):  # нужной версии мастер-ключа нет
        await vault.startup_check_with(K2)
    await vault.startup_check_with(K1)  # верный
    assert vault.enabled()
    # всё потеряно не было
    assert await get_history_text(CONNECTION_ID, CHAT, 1) == SECRET


async def test_startup_without_keys_and_without_encrypted_data_is_allowed(connection):
    await vault.startup_check_with("")
    assert not vault.enabled()
    await save_history(CONNECTION_ID, CHAT, 1, False, "открыто", NOW)
    assert (await raw_history(1)).text == "открыто" and (
        await raw_history(1)
    ).enc_ver is None


# ------------------------------ сбои ключа --------------------------------------------


async def test_unreadable_record_degrades_without_crash(ready):
    await save_history(CONNECTION_ID, CHAT, 1, False, SECRET, NOW, snapshot=snap())
    await OwnerKey.all().delete()
    vault._deks.clear()
    vault._active.clear()
    entry = await get_history_entry(CONNECTION_ID, CHAT, 1)
    assert entry["text"] is None and entry["payload"] is None  # содержимого нет
    assert entry["chat_id"] == CHAT and entry["kind"] == "text"  # метаданные целы
    await asyncio.sleep(0)
    assert OWNER_ID in vault.failed_owners  # состояние для alert data_key_missing
    assert (await raw_history(1)).enc_ver == 1  # шифротекст на месте — данные не стёрты


async def test_encryption_failure_never_writes_plaintext(ready, monkeypatch):
    async def broken(owner_id):
        raise RuntimeError("нет ключа")

    monkeypatch.setattr(vault, "active_key", broken)
    await save_history(CONNECTION_ID, CHAT, 1, False, SECRET, NOW, snapshot=snap())
    row = await raw_history(1)
    assert row.text is None and row.payload is None and row.raw_json is None
    assert row.chat_id == CHAT  # метаданные сохранены
    await log_archive_event(CONNECTION_ID, CHAT, 1, "deleted", SECRET, None, NOW)
    log = await ArchiveLog.first()
    assert log.old_text is None and log.event == "deleted"


async def test_failure_does_not_overwrite_existing_encrypted_row(ready, monkeypatch):
    await save_history(CONNECTION_ID, CHAT, 1, False, SECRET, NOW)
    good = (await raw_history(1)).text

    async def broken(owner_id):
        raise RuntimeError("сбой")

    monkeypatch.setattr(vault, "active_key", broken)
    await save_history(CONNECTION_ID, CHAT, 1, False, "правка", NOW)
    assert (await raw_history(1)).text == good


async def test_concurrent_first_writes_create_one_key(ready):
    await asyncio.gather(
        *(save_history(CONNECTION_ID, CHAT, i, False, SECRET, NOW) for i in range(1, 6))
    )
    assert await OwnerKey.filter(owner_id=OWNER_ID).count() == 1
    assert (await get_history_entry(CONNECTION_ID, CHAT, 5))["text"] == SECRET


# ------------------------------ поиск -------------------------------------------------


async def test_search_in_python_is_case_insensitive_and_bounded(ready, monkeypatch):
    for i, text in enumerate(("Привет Мир", "другое", "ПРИВЕТ снова", "ещё")):
        await log_archive_event(CONNECTION_ID, CHAT, i, "deleted", text, None, NOW + i)
    page, more = await get_archive_page(CONNECTION_ID, None, 10, search="привет")
    assert [e["old_text"] for e in page] == ["ПРИВЕТ снова", "Привет Мир"] and not more
    page, more = await get_archive_page(CONNECTION_ID, None, 1, search="привет")
    assert [e["old_text"] for e in page] == ["ПРИВЕТ снова"] and more
    # потолок просмотра: совпадение глубже лимита не находится
    monkeypatch.setattr(settings, "ARCHIVE_SEARCH_SCAN", 2)
    monkeypatch.setattr("app.features.archive.queries._SEARCH_BATCH", 2)
    page, _ = await get_archive_page(CONNECTION_ID, None, 10, search="привет")
    assert [e["old_text"] for e in page] == ["ПРИВЕТ снова"]


async def test_search_finds_legacy_rows_too(ready):
    vault.configure("")
    await log_archive_event(
        CONNECTION_ID, CHAT, 1, "deleted", "старая запись", None, NOW
    )
    vault.configure(K1)
    await log_archive_event(
        CONNECTION_ID, CHAT, 2, "deleted", "новая запись", None, NOW
    )
    page, _ = await get_archive_page(CONNECTION_ID, None, 10, search="ЗАПИСЬ")
    assert len(page) == 2


# ------------------------------ сквозные ----------------------------------------------


async def test_deleted_message_notice_and_ciphertext_in_db(ready, bot):
    msg = make_message(SECRET, chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)
    row = await raw_history(msg.message_id)
    assert row.enc_ver == 1 and row.text != SECRET

    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    (notice,) = bot.sent
    assert SECRET in notice["text"]  # уведомление с текстом
    log = await ArchiveLog.first()
    assert log.enc_ver == 1 and not contains_secret(log.old_text, log.old_snapshot)


async def test_edited_message_notice_and_edit_history(ready, bot):
    msg = make_message("первая версия", chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)
    edited = make_message("вторая версия", chat_id=CHAT, from_id=CHAT)
    edited.message_id = msg.message_id
    await on_business_edited(edited, bot)
    (notice,) = bot.sent
    plain = re.sub(r"<[^>]+>", "", notice["text"])  # «Было/Стало» подсвечивает отличия
    assert "первая версия" in plain and "вторая версия" in plain
    log = await ArchiveLog.first()
    assert log.old_text != "первая версия" and log.enc_ver == 1
    (edit,) = await get_edit_history(CONNECTION_ID, CHAT, msg.message_id)
    assert (edit["old_text"], edit["new_text"]) == ("первая версия", "вторая версия")


async def test_api_archive_search_media_and_export(ready, client, api_bot):
    await save_history(
        CONNECTION_ID, CHAT, 70, False, "x", NOW, media_type="photo", media_data=b"JPEG"
    )
    await log_archive_event(
        CONNECTION_ID,
        CHAT,
        70,
        "deleted",
        SECRET,
        None,
        NOW,
        media_type="photo",
        media_data=b"JPEG",
    )
    h = client.owner
    listing = (await client.get("/api/archive", headers=h)).json()
    assert listing["entries"][0]["old_text"] == SECRET
    found = (await client.get("/api/archive?search=ПАРОЛЬ", headers=h)).json()
    assert len(found["entries"]) == 1
    assert (await client.get("/api/archive?search=нетакого", headers=h)).json()[
        "entries"
    ] == []
    media = await client.get("/api/archive/1/media", headers=h)
    assert media.status_code == 200 and media.content == b"JPEG"

    for fmt in ("html", "csv", "json"):
        r = await client.post("/api/archive/export", headers=h, json={"format": fmt})
        assert r.status_code == 200 and r.json()["entries"] == 1
        assert SECRET.encode() in api_bot.documents[-1]["document"].data
