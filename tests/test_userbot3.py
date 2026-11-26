"""Архив: лимиты и сроки ПОЙМАННОГО по тарифу (задача 17.3)."""

import ast
import logging
import types
from pathlib import Path

import pytest

from app.features.alerts.models import Alert
from app.features.archive import capacity, queries
from app.features.archive.bot.deleted import on_business_deleted
from app.features.archive.bot.edited import on_business_edited
from app.features.archive.bot.limit_actions import on_limit_button
from app.features.archive.models import ArchiveLog
from app.features.limits import plans
from app.features.vault import service as vault
from app.platform.i18n import LOCALES
from app.platform.retention import run_retention_once
from app.platform.sources import userbot_connection_id
from app.platform.ttl_cache import clear_all
from config import settings
from db.models.module_settings import disable_module

from .conftest import (
    CONNECTION_ID,
    OWNER_ID,
    deleted_event,
    make_message,
    on_business_message,
    tg_file,
)

CHAT = 7
DAY = 86400
FILE = b"bytes:files/p"  # что отдаёт FakeBot при скачивании файла `p`


@pytest.fixture(autouse=True)
def fresh_reports(monkeypatch):
    """Память «уже предупредили» живёт в процессе: каждому тесту — чистая."""
    monkeypatch.setattr("app.features.limits.bot._reported", set())
    monkeypatch.setattr(capacity, "_reported", {})


@pytest.fixture
def cfg(monkeypatch):
    def apply(**values):
        for name, value in values.items():
            monkeypatch.setattr(settings, name, value)
        clear_all()

    return apply


@pytest.fixture
async def ready(connection, api_bot, alerts_bot, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", False)  # обычный путь уведомлений
    monkeypatch.setattr(settings, "KEEP_MEDIA_BYTES", True)  # файлы лежат в записи
    await disable_module(CONNECTION_ID, "scam")
    return connection


async def deleted_text(bot, text="привет"):
    msg = make_message(text, chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    return msg


async def deleted_photo(bot, name="p"):
    msg = make_message(chat_id=CHAT, from_id=CHAT, photo=[tg_file(name)])
    await on_business_message(msg, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    return msg


async def entries():
    return await ArchiveLog.all().order_by("log_id")


# --- планы и метрики -------------------------------------------------------------------
def test_plans_defaults_and_retention_pairs(cfg):
    assert plans.limit_for("free", "archive_entries") == 300
    assert plans.limit_for("free", "archive_media_bytes") == 100 * plans.MB
    assert plans.retention("free") == (14, 14)
    assert plans.retention("pro") == (30, 30)
    assert plans.retention("max") == (30, 30)
    assert plans.retention("admin") == (None, None)
    assert "stored_messages" not in plans.METRICS
    assert "media_bytes" not in plans.METRICS


def test_media_retention_never_exceeds_text_retention(cfg):
    cfg(PLAN_LIMITS_PRO="retention_days=7,retention_media_days=30")
    assert plans.retention("pro") == (7, 7)  # файл не живёт дольше записи
    cfg(PLAN_LIMITS_PRO="retention_days=90,retention_media_days=30")
    assert plans.retention("pro") == (90, 30)
    cfg(PLAN_LIMITS_PRO="retention_days=-1,retention_media_days=30")
    assert plans.retention("pro") == (None, 30)


def test_every_new_text_exists_in_all_languages():
    keys = (
        "limits.metric.archive_entries",
        "limits.metric.archive_media_bytes",
        "limits.metric.retention_media_days",
        "limits.effect.archive_full",
        "limits.unit.mb",
        "archive.limit.select",
        "archive.limit.files",
        "archive.limit.all",
        "archive.limit.confirm",
        "archive.limit.yes",
        "archive.limit.no",
        "archive.limit.files_done",
        "archive.limit.all_done",
        "archive.limit.nothing",
        "archive.limit.failed",
    )
    for locale, strings in LOCALES.items():
        for key in keys:
            assert key in strings, (locale, key)


def test_new_modules_do_not_import_aiogram_directly():
    root = Path(__file__).resolve().parent.parent / "app/features/archive"
    for name in ("capacity", "api_delete", "queries", "service"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            else:
                continue
            assert not [n for n in names if n.split(".")[0] == "aiogram"], name


# --- размер файла в записи ---------------------------------------------------------------
async def test_media_size_is_stored(ready, bot):
    await deleted_photo(bot)
    (row,) = await entries()
    assert row.media_size == len(FILE) and row.media_status == "saved"
    assert await queries.archive_usage([CONNECTION_ID]) == (1, len(FILE))


async def test_media_size_matches_ciphertext_overhead(ready, bot):
    """Формула бэкфилла миграции 26: шифротекст длиннее файла на 31 байт."""
    if not vault.enabled():
        pytest.skip("нужно шифрование (TEST_VAULT=1)")
    await deleted_photo(bot)
    raw = await ArchiveLog.all().values("media_data", "media_size", "enc_ver")
    assert raw[0]["enc_ver"] is not None
    assert len(bytes(raw[0]["media_data"])) - 31 == raw[0]["media_size"] == len(FILE)


# --- лимит записей: не пишем, уведомляем ---------------------------------------------------
async def test_full_archive_still_notifies_but_does_not_write(
    ready, bot, alerts_bot, cfg
):
    cfg(PLAN_LIMITS_FREE="archive_entries=1")
    await deleted_text(bot, "первое")
    await deleted_text(bot, "второе")
    assert len(await entries()) == 1  # второе в веб-архив не попало
    assert len(bot.sent) == 2  # а уведомления пришли оба
    assert len(alerts_bot.sent) == 1  # и один alert про лимит
    alert = await Alert.get(code="limit_reached:archive_entries")
    assert alert.count == 1


async def test_full_archive_deletes_nothing_old(ready, bot, cfg):
    cfg(PLAN_LIMITS_FREE="archive_entries=2")
    for text in ("a", "b", "c", "d"):
        await deleted_text(bot, text)
    rows = await entries()
    assert [r.old_text for r in await _opened(rows)] == ["a", "b"]


async def _opened(rows):
    opened = await vault.open_by_connection(
        "archive_log",
        CONNECTION_ID,
        [{"old_text": r.old_text, "enc_ver": r.enc_ver} for r in rows],
    )
    return [types.SimpleNamespace(**row) for row in opened]


async def test_full_archive_edit_notifies_without_log(ready, bot, cfg):
    cfg(PLAN_LIMITS_FREE="archive_entries=0")
    msg = make_message("до", chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)
    edited = make_message("после", chat_id=CHAT, from_id=CHAT)
    edited.message_id = msg.message_id
    await on_business_edited(edited, bot)
    assert await entries() == []
    assert len(bot.sent) == 1  # «Было/Стало» отправлено
    assert await Alert.filter(code="limit_reached:archive_entries").exists()


async def test_media_limit_keeps_row_without_file(ready, bot, alerts_bot, cfg):
    cfg(PLAN_LIMITS_FREE=f"archive_media_bytes={len(FILE) - 1}")
    await deleted_photo(bot)
    (row,) = await entries()
    assert row.media_data is None and row.media_size is None
    assert row.media_status == "limit"
    assert await Alert.filter(code="limit_reached:archive_media_bytes").exists()
    assert len(bot.media_sent) == 1  # файл показан уведомлением по file_id


async def test_media_limit_counts_existing_bytes(ready, bot, cfg):
    cfg(PLAN_LIMITS_FREE=f"archive_media_bytes={len(FILE) * 2}")
    await deleted_photo(bot)
    await deleted_photo(bot)
    await deleted_photo(bot)  # третий уже не помещается
    rows = await entries()
    assert [r.media_status for r in rows] == ["saved", "saved", "limit"]


async def test_admin_is_unlimited_and_makes_no_queries(ready, bot, cfg, monkeypatch):
    cfg(PLAN_LIMITS_FREE="archive_entries=0", ADMIN_USER_IDS=str(OWNER_ID))

    async def boom(owner_id):
        raise AssertionError("у администратора счётчики не считаются")

    monkeypatch.setattr(capacity, "usage", boom)
    await deleted_text(bot)
    assert len(await entries()) == 1


async def test_paid_plan_without_limits_writes(ready, bot, cfg, monkeypatch):
    from app.features.limits import queries as limit_queries

    await limit_queries.set_plan(OWNER_ID, "pro", "payment")
    clear_all()
    cfg(PLAN_LIMITS_FREE="archive_entries=0")
    await deleted_text(bot)
    assert len(await entries()) == 1


async def test_limit_check_failure_writes_and_reports(
    ready, bot, cfg, monkeypatch, caplog
):
    cfg(PLAN_LIMITS_FREE="archive_entries=1")

    async def boom(owner_id):
        raise RuntimeError("БД недоступна")

    monkeypatch.setattr(capacity, "usage", boom)
    with caplog.at_level(logging.ERROR, logger="archive.capacity"):
        await deleted_text(bot)
    assert len(await entries()) == 1  # данные важнее точности лимита
    record = next(r for r in caplog.records if r.name == "archive.capacity")
    assert record.exc_info  # попадёт в журнал наблюдаемости


async def test_repeated_denials_report_once(ready, bot, alerts_bot, cfg):
    cfg(PLAN_LIMITS_FREE="archive_entries=0")
    for _ in range(4):
        await deleted_text(bot)
    assert len(alerts_bot.sent) == 1
    assert (await Alert.get(code="limit_reached:archive_entries")).count == 1


# --- предупреждение и кнопки ----------------------------------------------------------------
def _buttons(message):
    return [b for row in message["reply_markup"].inline_keyboard for b in row]


async def test_alert_has_archive_buttons(ready, bot, alerts_bot, cfg):
    cfg(PLAN_LIMITS_FREE="archive_entries=0")
    await deleted_text(bot)
    alert = await Alert.get(code="limit_reached:archive_entries")
    buttons = _buttons(alerts_bot.sent[0])
    data = {b.callback_data for b in buttons if b.callback_data}
    assert {f"arl:files:{alert.id}", f"arl:all:{alert.id}"} <= data
    assert f"al:ok:{alert.id}" in data and f"al:mute:{alert.id}" in data
    web = next(b for b in buttons if b.web_app)
    assert web.web_app.url.endswith("/archive?select=1")
    assert "300" not in alerts_bot.sent[0]["text"]  # лимит free здесь переопределён
    assert "(0)" in alerts_bot.sent[0]["text"]


async def test_media_alert_has_no_delete_all_button(ready, bot, alerts_bot, cfg):
    cfg(PLAN_LIMITS_FREE="archive_media_bytes=1")
    await deleted_photo(bot)
    data = {b.callback_data for b in _buttons(alerts_bot.sent[0]) if b.callback_data}
    assert not [d for d in data if d.startswith("arl:all")]
    assert [d for d in data if d.startswith("arl:files")]
    assert "МБ" in alerts_bot.sent[0]["text"]


async def test_other_alerts_have_no_archive_buttons(database, alerts_bot):
    from app.features.alerts.bot import report

    await report(
        OWNER_ID, "limit_reached:mirrors", label="x", effect="y", limit="1", plan="free"
    )
    data = {b.callback_data for b in _buttons(alerts_bot.sent[0]) if b.callback_data}
    assert not [d for d in data if d.startswith("arl:")]


class Call:
    def __init__(self, data, user_id=OWNER_ID):
        self.data = data
        self.from_user = types.SimpleNamespace(id=user_id)
        self.answers, self.deleted, self.edits = [], 0, []
        self.message = types.SimpleNamespace(delete=self._delete, edit_text=self._edit)

    async def _delete(self):
        self.deleted += 1

    async def _edit(self, text, reply_markup=None):
        self.edits.append((text, reply_markup))

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


async def _full_alert(bot, cfg, texts=("a", "b", "c")):
    cfg(PLAN_LIMITS_FREE=f"archive_entries={len(texts)}")
    for text in texts:
        await deleted_text(bot, text)
    await deleted_text(bot, "лишнее")  # вызывает alert
    return await Alert.get(code="limit_reached:archive_entries")


async def test_delete_files_button(ready, bot, alerts_bot, cfg):
    cfg(PLAN_LIMITS_FREE="archive_media_bytes=100")
    await deleted_photo(bot)
    await deleted_photo(bot)
    cfg(PLAN_LIMITS_FREE="archive_media_bytes=1")
    await deleted_photo(bot)  # alert
    alert = await Alert.get(code="limit_reached:archive_media_bytes")
    call = Call(f"arl:files:{alert.id}")
    await on_limit_button(call)
    rows = await entries()
    assert len(rows) == 3  # записи остались
    assert all(r.media_data is None and r.media_size is None for r in rows)
    assert {r.media_status for r in rows} == {"deleted", "limit"}
    assert "Файлы удалены: 2" in call.edits[0][0]
    assert (await Alert.get(id=alert.id)).dismissed is True


async def test_delete_all_needs_confirmation(ready, bot, alerts_bot, cfg):
    alert = await _full_alert(bot, cfg)
    ask = Call(f"arl:all:{alert.id}")
    await on_limit_button(ask)
    assert len(await entries()) == 3  # пока ничего не удалено
    text, markup = ask.edits[0]
    assert "(3)" in text
    yes, no = markup.inline_keyboard[0]
    assert yes.text.endswith("3") and no.callback_data == f"arl:no:{alert.id}"
    assert yes.callback_data.startswith(f"arl:yes:{alert.id}:")

    done = Call(yes.callback_data)
    await on_limit_button(done)
    assert await entries() == []
    assert "Удалено записей: 3" in done.edits[0][0]
    assert (await Alert.get(id=alert.id)).dismissed is True


async def test_confirmed_delete_spares_newer_entries(ready, bot, alerts_bot, cfg):
    alert = await _full_alert(bot, cfg, texts=("a", "b"))
    ask = Call(f"arl:all:{alert.id}")
    await on_limit_button(ask)
    yes = ask.edits[0][1].inline_keyboard[0][0].callback_data
    cfg(PLAN_LIMITS_FREE="archive_entries=10")
    await deleted_text(bot, "новое после вопроса")
    await on_limit_button(Call(yes))
    left = await entries()
    assert len(left) == 1  # не то, что человек видел на экране подтверждения


async def test_cancel_removes_question_and_keeps_data(ready, bot, alerts_bot, cfg):
    alert = await _full_alert(bot, cfg)
    call = Call(f"arl:no:{alert.id}")
    await on_limit_button(call)
    assert call.deleted == 1 and len(await entries()) == 3
    assert (await Alert.get(id=alert.id)).dismissed is False


async def test_buttons_work_only_on_own_data(ready, bot, alerts_bot, cfg):
    alert = await _full_alert(bot, cfg)
    stranger = Call(f"arl:all:{alert.id}", user_id=999)
    await on_limit_button(stranger)
    assert "Архив уже пуст" in stranger.edits[0][0]
    await on_limit_button(Call(f"arl:yes:{alert.id}:999999", user_id=999))
    assert len(await entries()) == 3


async def test_garbage_callbacks_are_ignored(ready):
    for data in ("arl:all", "arl:all:x", "arl:yes:1:z", "arl:files:1:2:3", "arl"):
        call = Call(data)
        await on_limit_button(call)
        assert not call.edits and not call.deleted


async def test_button_failure_is_reported_not_raised(
    ready, bot, alerts_bot, cfg, monkeypatch, caplog
):
    alert = await _full_alert(bot, cfg)

    async def boom(*args, **kwargs):
        raise RuntimeError("x")

    monkeypatch.setattr("app.features.archive.bot.limit_actions.delete_entries", boom)
    call = Call(f"arl:files:{alert.id}")
    with caplog.at_level(logging.ERROR):
        await on_limit_button(call)
    assert call.answers and "Не удалось" in call.answers[-1]
    assert any(r.exc_info for r in caplog.records)


# --- API: удаление и использование -------------------------------------------------------------
async def test_api_delete_selected_entries(ready, bot, client):
    for text in ("a", "b", "c"):
        await deleted_text(bot, text)
    first, second, third = [r.log_id for r in await entries()]
    resp = await client.request(
        "DELETE", "/api/archive", json={"ids": [first, second]}, headers=client.owner
    )
    assert resp.status_code == 200 and resp.json() == {"count": 2, "freed_bytes": 0}
    assert [r.log_id for r in await entries()] == [third]


async def test_api_delete_files_only(ready, bot, client):
    await deleted_photo(bot)
    (row,) = await entries()
    resp = await client.request(
        "DELETE",
        "/api/archive",
        json={"ids": [row.log_id], "media_only": True},
        headers=client.owner,
    )
    assert resp.json() == {"count": 1, "freed_bytes": len(FILE)}
    (row,) = await entries()
    assert row.media_data is None and row.media_status == "deleted"
    again = await client.request(
        "DELETE",
        "/api/archive",
        json={"ids": [row.log_id], "media_only": True},
        headers=client.owner,
    )
    assert again.json() == {"count": 0, "freed_bytes": 0}


async def test_api_delete_ignores_foreign_entries(ready, bot, client):
    await deleted_text(bot)
    foreign = await ArchiveLog.create(
        connection_id="other-conn",
        chat_id=1,
        message_id=1,
        event="deleted",
        created_at=1,
    )
    mine = (await entries())[0]
    resp = await client.request(
        "DELETE",
        "/api/archive",
        json={"ids": [foreign.log_id, mine.log_id]},
        headers=client.owner,
    )
    assert resp.json()["count"] == 1
    assert await ArchiveLog.filter(log_id=foreign.log_id).exists()


async def test_api_delete_validates_body(ready, client):
    for body in ({"ids": []}, {"ids": list(range(501))}, {}, {"ids": ["x"]}):
        resp = await client.request(
            "DELETE", "/api/archive", json=body, headers=client.owner
        )
        assert resp.status_code == 422, body
    resp = await client.request("DELETE", "/api/archive", json={"ids": [1]})
    assert resp.status_code in (401, 403, 422)  # без initData


async def test_api_delete_covers_userbot_connection(ready, bot, client):
    row = await ArchiveLog.create(
        connection_id=userbot_connection_id(OWNER_ID),
        chat_id=-100,
        message_id=5,
        event="deleted",
        created_at=1,
    )
    resp = await client.request(
        "DELETE", "/api/archive", json={"ids": [row.log_id]}, headers=client.owner
    )
    assert resp.json()["count"] == 1


async def test_plan_endpoint_reports_archive_usage(ready, bot, client, cfg):
    await deleted_text(bot)
    await deleted_photo(bot)
    body = (await client.get("/api/plan", headers=client.owner)).json()
    by_metric = {row["metric"]: row for row in body["limits"]}
    assert by_metric["archive_entries"]["used"] == 2
    assert by_metric["archive_entries"]["limit"] == 300
    assert by_metric["archive_media_bytes"]["used"] == len(FILE)
    assert by_metric["retention_days"]["limit"] == 14
    assert by_metric["retention_media_days"]["limit"] == 14
    assert by_metric["retention_days"]["used"] is None


# --- очистка по сроку тарифа ---------------------------------------------------------------------
async def _row(connection_id, age_days, now, media=b"x" * 10):
    return await queries.log_archive_event(
        connection_id,
        CHAT,
        age_days,
        "deleted",
        f"t{age_days}",
        None,
        now - age_days * DAY,
        media_type="photo" if media else None,
        media_data=media,
    )


async def test_retention_by_plan_deletes_expired_entries(ready, cfg):
    now = 1_800_000_000
    old = await _row(CONNECTION_ID, 20, now)
    fresh = await _row(CONNECTION_ID, 1, now)
    ub_old = await _row(userbot_connection_id(OWNER_ID), 20, now)
    stats = await run_retention_once(now=now)
    assert stats["archive_plan_expired"] >= 2
    left = {r.log_id for r in await entries()}
    assert left == {fresh} and old not in left and ub_old not in left


async def test_retention_files_expire_before_entries(ready, cfg):
    cfg(PLAN_LIMITS_FREE="retention_days=30,retention_media_days=7")
    now = 1_800_000_000
    mid = await _row(CONNECTION_ID, 10, now)
    fresh = await _row(CONNECTION_ID, 2, now)
    await run_retention_once(now=now)
    rows = {r.log_id: r for r in await entries()}
    assert rows[mid].media_data is None and rows[mid].media_status == "expired"
    assert rows[mid].media_size is None  # запись осталась, файл ушёл
    assert rows[fresh].media_data is not None and rows[fresh].media_size == 10


async def test_retention_pro_keeps_longer(ready, cfg):
    from app.features.limits import queries as limit_queries

    await limit_queries.set_plan(OWNER_ID, "pro", "payment")
    clear_all()
    now = 1_800_000_000
    mid = await _row(CONNECTION_ID, 20, now)
    await _row(CONNECTION_ID, 40, now)  # старше 30 дней — удаляется
    await run_retention_once(now=now)
    assert {r.log_id for r in await entries()} == {mid}


async def test_retention_spares_admin(ready, cfg):
    cfg(ADMIN_USER_IDS=str(OWNER_ID))
    now = 1_800_000_000
    await _row(CONNECTION_ID, 400, now)
    await run_retention_once(now=now)
    assert len(await entries()) == 1


async def test_retention_ignores_unknown_connections(ready):
    now = 1_800_000_000
    await _row("ghost-connection", 400, now)
    await run_retention_once(now=now)
    assert len(await entries()) == 1  # владелец неизвестен: срок тарифа не применяем


async def test_retention_failure_is_logged_for_ops(ready, monkeypatch, caplog):
    async def boom(*args, **kwargs):
        raise RuntimeError("БД")

    monkeypatch.setattr("app.features.archive.retention.purge_connections_before", boom)
    await _row(CONNECTION_ID, 20, 1_800_000_000)
    with caplog.at_level(logging.ERROR):
        await run_retention_once(now=1_800_000_000)
    assert any(
        r.exc_info and "archive_plan_expired" in r.getMessage() for r in caplog.records
    )
