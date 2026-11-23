"""Юзербот.1: сессии, вход по QR, жизненный цикл, блокировка, ingest, API, чат."""

import asyncio
import logging
import os
import types
from pathlib import Path
from typing import ClassVar

import pytest
import pytest_asyncio
from tortoise import Tortoise

from app.features.history.ingest import ingest
from app.features.history.models import MessageHistory
from app.features.history.service import get_history_entry
from app.features.userbot import lock as lockmod
from app.features.userbot import login, queries, service
from app.features.userbot.errors import (
    PasswordInvalid,
    PasswordNeeded,
    SessionRevoked,
)
from app.features.userbot.manager import UserbotManager
from app.features.userbot.models import UserbotSession
from app.features.userbot.telethon_snapshot import build_snapshot, entities
from app.features.vault import service as vault
from app.platform.sources import (
    is_channel_peer,
    source_of,
    userbot_connection_id,
    userbot_owner,
)
from app.platform.tasks import _tasks
from config import settings
from db.models.connection import upsert_connection

from .conftest import NOW, OWNER_ID, TEST_MASTER_KEYS

SECRET = "1SESSIONSTRINGSECRETVALUE"


@pytest_asyncio.fixture
async def ub(database, monkeypatch):
    """Юзербот настроен, шифрование включено, состояние входа и менеджера чистое."""
    monkeypatch.setattr(settings, "TELEGRAM_API_ID", 1)
    monkeypatch.setattr(settings, "TELEGRAM_API_HASH", "hash")
    vault.configure(TEST_MASTER_KEYS)
    login.flows.clear()
    yield
    for flow in list(login.flows.values()):
        if flow.task:
            flow.task.cancel()
    login.flows.clear()
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def drain():
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


async def until(predicate, limit=3.0):
    loop = asyncio.get_running_loop()
    end = loop.time() + limit
    while loop.time() < end:
        if await predicate() if asyncio.iscoroutinefunction(predicate) else predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("условие не наступило")


async def put_session(owner=OWNER_ID, **kw):
    ok = await queries.save_session(
        owner,
        kw.pop("session", SECRET),
        tg_user_id=kw.pop("tg_user_id", 7),
        username=kw.pop("username", "me"),
        consent_at=NOW,
    )
    assert ok
    for key, value in kw.items():
        await UserbotSession.filter(owner_id=owner).update(**{key: value})


# --- источники ----------------------------------------------------------------------


def test_sources_helpers():
    assert userbot_connection_id(5) == "ub:5"
    assert userbot_owner("ub:5") == 5
    assert userbot_owner("conn-1") is None
    assert userbot_owner("ub:x") is None
    assert source_of("ub:5") == "userbot" and source_of("abc") == "bot"
    assert is_channel_peer(-1001234567890)
    assert not is_channel_peer(-123456) and not is_channel_peer(777)


async def test_vault_owner_of_userbot_connection(database):
    assert await vault.owner_of("ub:99") == 99


# --- хранение сессии ----------------------------------------------------------------


async def test_session_is_stored_encrypted_and_roundtrips(ub):
    await put_session()
    raw = await UserbotSession.get(owner_id=OWNER_ID)
    assert raw.enc_ver is not None and raw.session != SECRET
    assert SECRET not in raw.session
    assert await queries.get_session_string(OWNER_ID) == SECRET
    info = await queries.get_info(OWNER_ID)
    assert "session" not in info and info["tg_username"] == "me"


async def test_session_refused_without_encryption(ub):
    vault.configure("")
    ok = await queries.save_session(
        OWNER_ID, SECRET, tg_user_id=1, username=None, consent_at=NOW
    )
    assert ok is False
    assert await UserbotSession.all().count() == 0


async def test_revoked_status_drops_ciphertext(ub):
    await put_session()
    await queries.set_status(OWNER_ID, "revoked", error="revoked")
    row = await UserbotSession.get(owner_id=OWNER_ID)
    assert row.session is None and row.status == "revoked" and not row.connected


def test_unavailable_reason(monkeypatch, database):
    monkeypatch.setattr(settings, "TELEGRAM_API_ID", 0)
    assert service.unavailable_reason() == "not_configured"
    monkeypatch.setattr(settings, "TELEGRAM_API_ID", 1)
    monkeypatch.setattr(settings, "TELEGRAM_API_HASH", "h")
    vault.configure("")
    assert service.unavailable_reason() == "no_encryption"
    vault.configure(TEST_MASTER_KEYS)
    assert service.unavailable_reason() is None


# --- вход по QR ---------------------------------------------------------------------


class FakeGateway:
    def __init__(self, *, password=None, qr_timeouts=0, accept_after=0.0):
        self.password_needed = password is not None
        self.expected = password
        self.qr_timeouts = qr_timeouts
        self.accept_after = accept_after
        self.urls = []
        self.closed = False
        self.attempts = []

    async def start(self):
        self.urls.append("tg://login?token=T0")
        return self.urls[-1]

    async def wait(self, within):
        await asyncio.sleep(self.accept_after)
        if self.qr_timeouts > 0:
            self.qr_timeouts -= 1
            return False
        if self.password_needed:
            raise PasswordNeeded
        return True

    async def recreate(self):
        self.urls.append(f"tg://login?token=T{len(self.urls)}")
        return self.urls[-1]

    async def password(self, pw):
        self.attempts.append(pw)
        if pw != self.expected:
            raise PasswordInvalid
        self.password_needed = False

    async def identity(self):
        return 7, "me"

    def session_string(self):
        return SECRET

    async def close(self):
        self.closed = True


async def run_login(gateway):
    flow = await login.start(OWNER_ID, NOW, lambda: gateway)
    return flow


async def test_login_qr_success_saves_session(ub):
    gw = FakeGateway(qr_timeouts=1)
    flow = await run_login(gw)
    await until(lambda: flow.state in (login.DONE, login.ERROR))
    assert flow.state == login.DONE and gw.closed
    assert len(gw.urls) == 2 and flow.qr_version == 2  # QR обновился один раз
    assert await queries.get_session_string(OWNER_ID) == SECRET


async def test_login_view_hides_qr_after_done(ub):
    flow = await run_login(FakeGateway())
    await until(lambda: flow.state == login.DONE)
    assert flow.view()["qr_url"] is None


async def test_login_password_flow_retries_then_succeeds(ub):
    gw = FakeGateway(password="right")
    flow = await run_login(gw)
    await until(lambda: flow.state == login.PASSWORD)
    assert await login.submit_password(OWNER_ID, "wrong")
    await until(lambda: flow.error == "invalid_password")
    assert flow.state == login.PASSWORD
    assert await login.submit_password(OWNER_ID, "right")
    await until(lambda: flow.state == login.DONE)
    assert gw.attempts == ["wrong", "right"]


async def test_login_too_many_wrong_passwords(ub):
    flow = await run_login(FakeGateway(password="right"))
    await until(lambda: flow.state == login.PASSWORD)
    for _ in range(login.MAX_PASSWORD_TRIES):
        await login.submit_password(OWNER_ID, "x")
        await asyncio.sleep(0.05)
    await until(lambda: flow.state == login.ERROR)
    assert flow.error == "too_many_attempts"
    assert await UserbotSession.all().count() == 0


async def test_password_rejected_when_not_waiting(ub):
    assert not await login.submit_password(OWNER_ID, "x")


async def test_login_timeout(ub, monkeypatch):
    monkeypatch.setattr(login, "LOGIN_TTL", 0.1)
    gw = FakeGateway(accept_after=5)
    flow = await run_login(gw)
    await until(lambda: flow.state == login.ERROR)
    assert flow.error == "expired" and gw.closed


async def test_login_storage_error_without_encryption(ub):
    flow = await run_login(FakeGateway())
    vault.configure("")
    await until(lambda: flow.state in (login.DONE, login.ERROR))
    assert flow.state == login.ERROR and flow.error == "storage"
    assert await UserbotSession.all().count() == 0


async def test_start_login_is_idempotent_while_active(ub):
    gw = FakeGateway(accept_after=0.3)
    first = await run_login(gw)
    again = await login.start(OWNER_ID, NOW, lambda: FakeGateway())
    assert again is first


async def test_session_string_never_logged(ub, caplog):
    caplog.set_level(logging.DEBUG)

    class Boom(FakeGateway):
        async def identity(self):
            raise RuntimeError("boom")

    flow = await run_login(Boom())
    await until(lambda: flow.state == login.ERROR)
    flow2 = await run_login(FakeGateway())
    await until(lambda: flow2.state == login.DONE)
    assert SECRET not in caplog.text
    assert "tg://login" not in caplog.text


async def test_service_start_login_rules(ub, monkeypatch):
    spawned = []

    async def fake_start(owner, consent_at, factory=None):
        spawned.append(owner)

    monkeypatch.setattr(login, "start", fake_start)
    assert await service.start_login(OWNER_ID) is None and spawned == [OWNER_ID]
    await put_session()
    assert await service.start_login(OWNER_ID) == "already_connected"
    await queries.set_status(OWNER_ID, "revoked")
    assert await service.start_login(OWNER_ID) is None  # после отзыва можно заново
    await queries.set_status(OWNER_ID, "removing")
    assert await service.start_login(OWNER_ID) == "removing"


# --- менеджер ------------------------------------------------------------------------


class FakeClient:
    registry: ClassVar[list] = []

    def __init__(self, session, *, user_id=7, fail=None):
        self.session = session
        self.user_id = user_id
        self.fail = fail
        self.closed = False
        self.logged_out = False
        self.changed = False
        self._gone = asyncio.Event()
        FakeClient.registry.append(self)

    async def connect(self):
        if self.fail:
            raise self.fail
        return self.user_id, "me"

    async def wait_disconnected(self):
        await self._gone.wait()

    def session_changed(self):
        return self.changed

    def session_string(self):
        return "NEW-" + self.session

    async def log_out(self):
        self.logged_out = True
        return True

    async def close(self):
        self.closed = True


@pytest.fixture
def make_manager(ub):
    FakeClient.registry = []

    def build(**client_kw):
        return UserbotManager(client_factory=lambda s: FakeClient(s, **client_kw))

    return build


async def test_reconcile_starts_client_and_marks_connected(make_manager):
    await put_session()
    mgr = make_manager()
    await mgr.reconcile()
    assert mgr.is_running(OWNER_ID)
    assert FakeClient.registry[0].session == SECRET
    assert (await queries.get_info(OWNER_ID))["connected"] is True
    await mgr.stop_all()
    assert FakeClient.registry[0].closed and not mgr.is_running(OWNER_ID)


async def test_stop_saves_changed_session(make_manager):
    await put_session()
    mgr = make_manager()
    await mgr.reconcile()
    FakeClient.registry[0].changed = True
    await mgr.stop_all()
    assert await queries.get_session_string(OWNER_ID) == "NEW-" + SECRET


async def test_revoked_session_marked_and_alerted(make_manager, alerts_bot):
    await put_session()
    mgr = make_manager(fail=SessionRevoked("x"))
    await mgr.reconcile()
    row = await UserbotSession.get(owner_id=OWNER_ID)
    assert row.status == "revoked" and row.session is None
    assert not mgr.is_running(OWNER_ID)
    from app.features.alerts.models import Alert

    assert await Alert.filter(code="userbot_session_revoked").count() == 1
    assert alerts_bot.sent  # владельцу ушло сообщение


async def test_foreign_account_session_is_revoked(make_manager):
    await put_session(tg_user_id=7)
    mgr = make_manager(user_id=8)
    await mgr.reconcile()
    assert (await UserbotSession.get(owner_id=OWNER_ID)).status == "revoked"
    assert FakeClient.registry[0].closed


async def test_failures_back_off_and_alert_after_three(make_manager):
    await put_session()
    mgr = make_manager(fail=ConnectionError("net"))
    await mgr.reconcile()
    first = mgr._next_try[OWNER_ID]
    await mgr.reconcile()  # пауза ещё идёт: повторной попытки нет
    assert len(FakeClient.registry) == 1
    for _ in range(2):
        mgr._next_try[OWNER_ID] = 0
        await mgr.reconcile()
    assert len(FakeClient.registry) == 3
    assert mgr._next_try[OWNER_ID] > first or mgr._failures[OWNER_ID] == 3
    from app.features.alerts.models import Alert

    assert await Alert.filter(code="userbot_disconnected").count() == 1
    info = await queries.get_info(OWNER_ID)
    assert info["connected"] is False and info["last_error"] == "ConnectionError"


async def test_remove_logs_out_and_deletes_row(make_manager):
    await put_session()
    mgr = make_manager()
    await mgr.reconcile()
    await queries.set_status(OWNER_ID, "removing")
    await mgr.reconcile()
    assert await UserbotSession.all().count() == 0
    assert any(c.logged_out for c in FakeClient.registry)
    assert not mgr.is_running(OWNER_ID)


async def test_lost_connection_restarts_with_backoff(make_manager):
    await put_session()
    mgr = make_manager()
    await mgr.reconcile()
    FakeClient.registry[0]._gone.set()
    await until(lambda: not mgr.is_running(OWNER_ID))
    assert (await queries.get_info(OWNER_ID))["connected"] is False
    assert mgr._next_try[OWNER_ID] > 0


async def test_alert_states_follow_row(ub):
    from app.features.alerts.states import still_active

    await put_session()
    assert await still_active(OWNER_ID, "userbot_disconnected")
    await queries.set_connected(OWNER_ID, True)
    assert not await still_active(OWNER_ID, "userbot_disconnected")
    await queries.set_status(OWNER_ID, "revoked")
    assert await still_active(OWNER_ID, "userbot_session_revoked")


class StubLock:
    def __init__(self, grant=True):
        self.grant = grant
        self.lost = asyncio.Event()
        self.alive = True
        self.released = False

    async def acquire(self):
        return self.grant

    async def check(self):
        return self.alive

    async def release(self):
        self.released = True


async def test_run_starts_only_under_lock_and_stops_when_lost(ub, monkeypatch):
    monkeypatch.setattr("app.features.userbot.manager.LOCK_RETRY", 0.01)
    monkeypatch.setattr("app.features.userbot.manager.TICK", 0.02)
    await put_session()
    FakeClient.registry = []
    lock = StubLock(grant=False)
    mgr = UserbotManager(
        client_factory=lambda s: FakeClient(s), lock_factory=lambda: lock
    )
    task = asyncio.create_task(mgr.run())
    await asyncio.sleep(0.1)
    assert (
        not FakeClient.registry and not mgr.holds_lock
    )  # блокировки нет — клиентов нет
    lock.grant = True
    await until(lambda: mgr.is_running(OWNER_ID))
    assert mgr.holds_lock
    lock.alive = False  # потеря блокировки
    await until(lambda: not mgr.is_running(OWNER_ID))
    assert FakeClient.registry[0].closed and lock.released
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


async def test_run_idle_without_api_credentials(ub, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_API_ID", 0)
    mgr = UserbotManager(lock_factory=lambda: pytest.fail("блокировку брать не надо"))
    await asyncio.wait_for(mgr.run(), timeout=1)


# --- блокировка ---------------------------------------------------------------------


async def test_local_lock_is_exclusive():
    first, second = lockmod.LocalLock(), lockmod.LocalLock()
    assert await first.acquire()
    assert not await second.acquire()
    await first.release()
    assert await second.acquire()
    await second.release()


def test_pg_kwargs_parses_tortoise_dsn():
    kw = lockmod._pg_kwargs("asyncpg://u:p%40ss@h.neon.tech/db?ssl=true")
    assert kw["host"] == "h.neon.tech" and kw["port"] == 5432
    assert kw["user"] == "u" and kw["password"] == "p@ss" and kw["ssl"] is True
    assert kw["database"] == "db"
    assert lockmod._pg_kwargs("asyncpg://u@h/db")["ssl"] is None


@pytest.mark.skipif(
    not lockmod.is_postgres(os.environ.get("TEST_DB_URL", "")),
    reason="нужен Postgres (TEST_DB_URL)",
)
async def test_pg_advisory_lock_is_exclusive_and_detects_loss():
    dsn = os.environ["TEST_DB_URL"]
    first, second = lockmod.PgAdvisoryLock(dsn), lockmod.PgAdvisoryLock(dsn)
    assert await first.acquire()
    assert await first.check()
    assert not await second.acquire()  # второй процесс клиентов не запустит
    first._conn.terminate()  # соединение умерло -> сервер снял блокировку
    await asyncio.sleep(0.1)
    assert not await first.check() and first.lost.is_set()
    assert await second.acquire()
    await second.release()
    await first.release()


# --- ingest --------------------------------------------------------------------------

UB_CONN = userbot_connection_id(OWNER_ID)


def snap(text="hello"):
    return {"kind": "text", "text": text, "entities": None}


async def test_ingest_userbot_group_is_encrypted_under_owner(ub):
    saved = await ingest(
        source="userbot",
        connection_id=UB_CONN,
        chat_id=-100123,
        message_id=5,
        is_owner=False,
        text="тайна",
        ts=NOW,
        snapshot=snap("тайна"),
    )
    assert saved
    raw = await MessageHistory.get(connection_id=UB_CONN, message_id=5)
    assert raw.enc_ver is not None and raw.text != "тайна"
    entry = await get_history_entry(UB_CONN, -100123, 5)
    assert entry["text"] == "тайна"


async def test_ingest_userbot_skips_private_chat_when_business_covers(ub):
    await upsert_connection("conn-1", OWNER_ID, OWNER_ID, True)
    saved = await ingest(
        source="userbot",
        connection_id=UB_CONN,
        chat_id=555,
        message_id=1,
        is_owner=False,
        text="x",
        ts=NOW,
        snapshot=snap("x"),
    )
    assert saved is False and await MessageHistory.all().count() == 0


async def test_ingest_userbot_private_chat_saved_without_business(ub):
    saved = await ingest(
        source="userbot",
        connection_id=UB_CONN,
        chat_id=555,
        message_id=1,
        is_owner=False,
        text="x",
        ts=NOW,
        snapshot=snap("x"),
    )
    assert saved and await MessageHistory.all().count() == 1


async def test_ingest_bot_source_always_saves(connection):
    saved = await ingest(
        source="bot",
        connection_id="conn-1",
        chat_id=555,
        message_id=1,
        is_owner=False,
        text="x",
        ts=NOW,
        snapshot=snap("x"),
    )
    assert saved


# --- снимок Telethon -----------------------------------------------------------------


def E(name, **kw):
    return type(name, (), kw)()


def test_entities_mapping_to_bot_api_format():
    msg = types.SimpleNamespace(
        entities=[
            E("MessageEntityBold", offset=0, length=3),
            E("MessageEntityTextUrl", offset=4, length=2, url="https://a.b?x=1&y=2"),
            E("MessageEntityCustomEmoji", offset=7, length=2, document_id=555),
            E("MessageEntityMentionName", offset=9, length=1, user_id=42),
            E("MessageEntityBlockquote", offset=10, length=3, collapsed=True),
            E("MessageEntityUnknownFuture", offset=0, length=1),
        ]
    )
    out = entities(msg)
    assert out[0] == {"type": "bold", "offset": 0, "length": 3}
    assert out[1]["type"] == "text_link" and out[1]["url"].endswith("y=2")
    assert out[2]["custom_emoji_id"] == "555"
    assert out[3]["user"] == {"id": 42}
    assert out[4]["type"] == "expandable_blockquote"
    assert len(out) == 5  # неизвестная сущность пропущена


def fake_msg(**kw):
    base = {
        "message": None,
        "entities": None,
        "grouped_id": None,
        "file": None,
        "media": None,
    }
    return types.SimpleNamespace(**{**base, **kw})


def test_snapshot_kinds():
    text = build_snapshot(fake_msg(message="hi"))
    assert text["kind"] == "text" and text["file_id"] is None
    f = types.SimpleNamespace(size=10, mime_type="video/mp4", name="a.mp4", duration=3)
    video = build_snapshot(fake_msg(video=True, file=f, message="cap", grouped_id=9))
    assert video["kind"] == "video" and video["media_group_id"] == "9"
    assert video["file_size"] == 10 and video["payload"]["duration"] == 3
    # у голосового есть и document — голосовое должно победить
    voice = build_snapshot(fake_msg(voice=True, document=True, file=f))
    assert voice["kind"] == "voice"
    geo = types.SimpleNamespace(lat=1.5, long=2.5)
    assert build_snapshot(fake_msg(geo=geo))["kind"] == "location"
    assert build_snapshot(fake_msg(media=object()))["kind"] == "other"
    assert build_snapshot(fake_msg()) is None  # служебное


# --- API -----------------------------------------------------------------------------


async def test_api_status_when_unconfigured(client, monkeypatch):
    monkeypatch.setattr(settings, "TELEGRAM_API_ID", 0)
    data = (await client.get("/api/userbot", headers=client.owner)).json()
    assert data["reason"] == "not_configured" and data["status"] == "none"
    resp = await client.post(
        "/api/userbot/login", json={"consent": True}, headers=client.owner
    )
    assert (
        resp.status_code == 409 and resp.json()["detail"]["reason"] == "not_configured"
    )


async def test_api_requires_consent(client, ub):
    resp = await client.post(
        "/api/userbot/login", json={"consent": False}, headers=client.owner
    )
    assert resp.status_code == 400


async def test_api_login_flow_returns_qr_then_connected(client, ub, monkeypatch):
    gateway = FakeGateway(accept_after=0.2)
    monkeypatch.setattr(login, "_default_gateway", lambda: gateway)
    # вход берёт фабрику по умолчанию в момент вызова start()
    monkeypatch.setattr(
        login,
        "start",
        lambda owner, consent_at, factory=None: _start_with(owner, consent_at, gateway),
    )
    resp = await client.post(
        "/api/userbot/login", json={"consent": True}, headers=client.owner
    )
    assert resp.status_code == 200
    await until(lambda: login.flows[OWNER_ID].state == login.QR)
    data = (await client.get("/api/userbot", headers=client.owner)).json()
    assert data["status"] == "login" and data["login"]["state"] == "qr"
    assert data["login"]["qr"].startswith("data:image/png;base64,")
    await until(lambda: login.flows[OWNER_ID].state == login.DONE)
    data = (await client.get("/api/userbot", headers=client.owner)).json()
    assert data["status"] == "connecting" and data["username"] == "me"
    assert SECRET not in str(data)


_real_start = login.start


async def _start_with(owner, consent_at, gateway):
    return await _real_start(owner, consent_at, lambda: gateway)


async def test_api_password_endpoint(client, ub, monkeypatch):
    resp = await client.post(
        "/api/userbot/login/password", json={"password": "x"}, headers=client.owner
    )
    assert resp.status_code == 409


async def test_api_delete_revoked_removes_row_immediately(client, ub):
    await put_session()
    await queries.set_status(OWNER_ID, "revoked")
    data = (await client.delete("/api/userbot", headers=client.owner)).json()
    assert data["status"] == "none" and await UserbotSession.all().count() == 0


async def test_api_delete_active_waits_for_lock_holder(client, ub, monkeypatch):
    await put_session()
    mgr = UserbotManager(client_factory=lambda s: FakeClient(s))
    monkeypatch.setattr("app.features.userbot.service.manager", mgr)
    monkeypatch.setattr(service, "REMOVE_WAIT", 3)
    await mgr.reconcile()
    task = asyncio.create_task(client.delete("/api/userbot", headers=client.owner))
    await until(lambda: mgr._wake.is_set())  # API разбудил менеджер
    await mgr.reconcile()
    data = (await task).json()
    assert data["status"] == "none" and await UserbotSession.all().count() == 0


# --- чат -----------------------------------------------------------------------------


async def test_chat_status_view_by_state(ub):
    from app.features.userbot.bot import _status_view

    text, kb = await _status_view(OWNER_ID, "ru")
    assert "Не подключён" in text
    assert kb.inline_keyboard[0][0].callback_data == "ub:connect"
    await put_session()
    await queries.set_connected(OWNER_ID, True)
    text, kb = await _status_view(OWNER_ID, "ru")
    assert "Подключён" in text and "@me" in text
    assert kb.inline_keyboard[0][0].callback_data == "ub:off"
    vault.configure("")
    text, kb = await _status_view(OWNER_ID, "ru")
    assert "DATA_MASTER_KEYS" in text and kb.inline_keyboard == []


@pytest.mark.parametrize("lang", ["ru", "en", "uk"])
def test_chat_texts_present_in_all_languages(lang):
    from app.platform.i18n import LOCALES

    for key in (
        "userbot.consent",
        "userbot.qr.caption",
        "userbot.password",
        "userbot.error.failed",
        "userbot.btn.off",
        "alert.userbot_disconnected.title",
        "alert.userbot_session_revoked.text",
    ):
        assert key in LOCALES[lang], (lang, key)


# --- раскладка ------------------------------------------------------------------------


def test_telethon_imported_only_by_adapter_files():
    root = Path(__file__).resolve().parent.parent
    allowed = {"telethon_adapter.py"}
    offenders = []
    for path in list(root.glob("app/**/*.py")) + list(root.glob("commands/**/*.py")):
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if "import telethon" in text or "from telethon" in text:
            offenders.append(str(path.relative_to(root)))
    assert offenders == []


def test_userbot_logic_layers_do_not_import_aiogram():
    import ast

    root = Path(__file__).resolve().parent.parent / "app/features/userbot"
    for name in ("service", "queries", "login", "manager", "lock", "models"):
        tree = ast.parse((root / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            module = getattr(node, "module", None) or ""
            names = [a.name for a in getattr(node, "names", [])]
            assert "aiogram" not in module and "aiogram" not in names, name


def test_userbot_columns_listed_in_vault_tables():
    from app.features.vault.tables import TABLES

    assert TABLES["userbot_sessions"].columns == {"session": "text"}
    assert "enc_ver" in UserbotSession._meta.fields_map
    assert Tortoise is not None
