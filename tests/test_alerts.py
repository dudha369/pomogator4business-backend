"""Фича alerts: пауза, события и состояния, «Больше не показывать», подключённые места."""

import asyncio
from pathlib import Path
import types

import pytest

from app.features.alerts import service
from app.features.alerts.bot import on_alert_button, report
from app.features.alerts.catalog import CATALOG, cooldown_seconds
from app.features.alerts.models import Alert, AlertMute
from app.platform.i18n import LOCALES
from app.platform.tasks import _tasks
from app.platform.telegram.context import CommandContext

from .conftest import NOW, OWNER_ID, init_data_headers, make_message

COOLDOWN = cooldown_seconds("no_delete_right")


# --- каталог и тексты ----------------------------------------------------------------
def test_every_code_has_texts_in_all_languages():
    for locale, strings in LOCALES.items():
        for code in CATALOG:
            assert f"alert.{code}.title" in strings, (locale, code)
            assert f"alert.{code}.text" in strings, (locale, code)
        for key in ("alert.btn.ok", "alert.btn.mute", "alert.toast.ok"):
            assert key in strings, (locale, key)


def test_service_layer_does_not_import_aiogram():
    import importlib

    for name in ("catalog", "models", "service", "states"):
        module = importlib.import_module(f"app.features.alerts.{name}")
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "import aiogram" not in source and "from aiogram" not in source, name


# --- пауза и счётчик -----------------------------------------------------------------
async def test_first_report_notifies_and_repeat_waits(database):
    first = await service.record(OWNER_ID, "no_delete_right", {"name": "A"}, now=NOW)
    assert first is not None
    assert (
        await service.record(OWNER_ID, "no_delete_right", {"name": "B"}, now=NOW + 60)
        is None
    )
    row = await Alert.get(owner_id=OWNER_ID, code="no_delete_right")
    assert (row.count, row.details) == (2, {"name": "B"})  # событие считает повторы

    again = await service.record(
        OWNER_ID, "no_delete_right", {"name": "C"}, now=NOW + COOLDOWN
    )
    assert again is not None and again.count == 3


async def test_dismissed_event_comes_back_after_cooldown(database):
    alert = await service.record(OWNER_ID, "no_delete_right", {}, now=NOW)
    assert await service.dismiss(OWNER_ID, alert.id)
    assert await service.list_active(OWNER_ID) == []
    await service.record(OWNER_ID, "no_delete_right", {}, now=NOW + COOLDOWN)
    row = await Alert.get(id=alert.id)
    assert row.dismissed is False


async def test_state_inside_cooldown_writes_nothing(database):
    await service.record(OWNER_ID, "ai_no_key", {}, now=NOW)
    assert await service.record(OWNER_ID, "ai_no_key", {}, now=NOW + 5) is None
    assert (await Alert.get(code="ai_no_key")).count == 1


async def test_codes_are_independent_per_subject(database):
    assert await service.record(
        OWNER_ID, "command_failed:dice", {"name": "dice"}, now=NOW
    )
    assert await service.record(
        OWNER_ID, "command_failed:flip", {"name": "flip"}, now=NOW
    )
    assert not await service.record(OWNER_ID, "command_failed:dice", {}, now=NOW + 10)
    assert await service.record(OWNER_ID, "command_failed:dice", {}, now=NOW + 3600)


async def test_unknown_code_raises_in_service_but_report_swallows(database, alerts_bot):
    with pytest.raises(KeyError):
        await service.record(OWNER_ID, "typo", {})
    await report(OWNER_ID, "typo")  # не бросает
    assert alerts_bot.sent == []


# --- «Больше не показывать» ------------------------------------------------------------
async def test_mute_silences_and_unmute_restores(database):
    alert = await service.record(OWNER_ID, "no_delete_right", {}, now=NOW)
    assert await service.mute(OWNER_ID, alert.id) == "no_delete_right"
    assert await Alert.filter(owner_id=OWNER_ID).count() == 0
    assert (
        await service.record(OWNER_ID, "no_delete_right", {}, now=NOW + 99999) is None
    )
    assert await service.list_muted(OWNER_ID) == ["no_delete_right"]

    assert await service.unmute(OWNER_ID, "no_delete_right")
    assert await service.record(OWNER_ID, "no_delete_right", {}, now=NOW + 99999)


async def test_cannot_touch_someone_elses_alert(database):
    alert = await service.record(OWNER_ID, "no_delete_right", {}, now=NOW)
    assert await service.mute(999, alert.id) is None
    assert await service.dismiss(999, alert.id) is False
    assert await AlertMute.all().count() == 0


# --- сообщение и кнопки ----------------------------------------------------------------
async def test_report_sends_plain_message_with_two_buttons(database, alerts_bot):
    await report(OWNER_ID, "command_failed:dice", name="dice")
    msg = alerts_bot.sent[0]
    assert msg["chat_id"] == OWNER_ID and msg["parse_mode"] is None
    assert ".dice" in msg["text"]
    buttons = msg["reply_markup"].inline_keyboard[0]
    assert [b.text for b in buttons] == ["Понятно", "Больше не показывать"]
    alert_id = (await Alert.get(code="command_failed:dice")).id
    assert [b.callback_data for b in buttons] == [
        f"al:ok:{alert_id}",
        f"al:mute:{alert_id}",
    ]
    await report(OWNER_ID, "command_failed:dice", name="dice")
    assert len(alerts_bot.sent) == 1


class FakeCall:
    def __init__(self, data, user_id=OWNER_ID):
        self.data = data
        self.from_user = types.SimpleNamespace(id=user_id)
        self.answers, self.deleted = [], 0
        self.message = types.SimpleNamespace(delete=self._delete)

    async def _delete(self):
        self.deleted += 1

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


async def test_ok_button_dismisses_and_removes_message(database, alerts_bot):
    await report(OWNER_ID, "no_delete_right", name="A")
    alert = await Alert.get(code="no_delete_right")
    call = FakeCall(f"al:ok:{alert.id}")
    await on_alert_button(call)
    assert (await Alert.get(id=alert.id)).dismissed is True
    assert call.deleted == 1 and call.answers == ["Ок"]


async def test_mute_button_mutes(database, alerts_bot):
    await report(OWNER_ID, "no_delete_right", name="A")
    alert = await Alert.get(code="no_delete_right")
    await on_alert_button(FakeCall(f"al:mute:{alert.id}"))
    assert await service.list_muted(OWNER_ID) == ["no_delete_right"]


async def test_garbage_callback_is_ignored(database):
    for data in ("al:ok", "al:zzz:1", "al:ok:x", "al:ok:1:2"):
        call = FakeCall(data)
        await on_alert_button(call)
        assert call.deleted == 0


# --- подключённые места ------------------------------------------------------------------
async def test_command_failure_goes_through_alerts(
    connection, bot, alerts_bot, monkeypatch
):
    from app.platform.telegram.registry import registry

    from .conftest import on_business_message

    async def boom(ctx):
        raise RuntimeError("x")

    monkeypatch.setattr(registry.find("ping"), "handler", boom)
    for _ in range(2):
        await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert len(alerts_bot.sent) == 1 and ".ping" in alerts_bot.sent[0]["text"]
    assert (await Alert.get(code="command_failed:ping")).count == 2


async def _drain():
    while _tasks:
        await asyncio.gather(*list(_tasks))


async def test_guest_command_without_right_reports_once(connection, alerts_bot):
    msg = make_message(".x", chat_id=7, from_id=7)
    ctx = CommandContext(bot=alerts_bot, message=msg, connection=connection, args="")
    await ctx.present("игра")
    await ctx.present("игра")
    await _drain()
    assert len([m for m in alerts_bot.sent if "alert" not in m]) >= 1
    notices = [m for m in alerts_bot.sent if m.get("reply_markup")]
    assert len(notices) == 1


async def test_guest_command_with_right_does_not_report(connection, alerts_bot):
    conn = {**connection, "rights_json": '{"can_delete_all_messages": true}'}
    msg = make_message(".x", chat_id=7, from_id=7)
    await CommandContext(bot=alerts_bot, message=msg, connection=conn, args="").present(
        "игра"
    )
    await _drain()
    assert await Alert.all().count() == 0


# --- состояния сами исчезают -------------------------------------------------------------
async def test_emoji_state_resolves_when_access_is_back(client):
    from app.features.emoji_clock.queries import set_emoji_status_granted

    await report(OWNER_ID, "emoji_access_revoked")
    r = (await client.get("/api/alerts", headers=client.owner)).json()
    assert [a["code"] for a in r["alerts"]] == ["emoji_access_revoked"]

    await set_emoji_status_granted(OWNER_ID, True)
    r = (await client.get("/api/alerts", headers=client.owner)).json()
    assert r["alerts"] == []
    assert await Alert.all().count() == 0


async def test_ai_state_follows_key_and_setting(client, monkeypatch):
    from app.features.ai import service as ai
    from app.features.ai.queries import upsert_ai_settings

    await upsert_ai_settings(OWNER_ID, enabled=True)
    monkeypatch.setattr(ai, "is_configured", lambda: False)
    await report(OWNER_ID, "ai_no_key")
    assert (
        len((await client.get("/api/alerts", headers=client.owner)).json()["alerts"])
        == 1
    )
    monkeypatch.setattr(ai, "is_configured", lambda: True)
    assert (await client.get("/api/alerts", headers=client.owner)).json()[
        "alerts"
    ] == []


async def test_mirror_state_checks_manager(client):
    from app.features.mirror.manager import mirror_manager
    from app.features.mirror.queries import save_mirror

    await save_mirror(OWNER_ID, b"x", 1, "m", NOW)
    await report(OWNER_ID, "mirror_not_running", reason="webhook_failed")
    body = (await client.get("/api/alerts", headers=client.owner)).json()
    assert body["alerts"][0]["details"] == {"reason": "webhook_failed"}

    mirror_manager._bots[OWNER_ID] = object()
    try:
        assert (await client.get("/api/alerts", headers=client.owner)).json()[
            "alerts"
        ] == []
    finally:
        mirror_manager._bots.pop(OWNER_ID, None)


async def test_start_all_reports_broken_mirror(database, alerts_bot):
    from app.features.mirror.manager import MirrorManager
    from app.features.mirror.queries import save_mirror

    await save_mirror(OWNER_ID, b"not-a-token", 1, "m", NOW)
    await MirrorManager().start_all()
    assert (await Alert.get(code="mirror_not_running")).details == {
        "reason": "token_invalid"
    }


async def test_connect_mirror_resolves_state(database, monkeypatch):
    from app.features.mirror import setup as mirror_setup

    await report(OWNER_ID, "mirror_not_running", reason="x")

    async def ok(*a, **k):
        return None

    class Me:
        id, username = 5, "m_bot"

    class B:
        def __init__(self, token):
            pass

        async def get_me(self):
            return Me

        class session:
            @staticmethod
            async def close():
                pass

    monkeypatch.setattr(mirror_setup, "AiogramBot", B)
    monkeypatch.setattr(mirror_setup.mirror_manager, "start_mirror", ok)
    monkeypatch.setattr(mirror_setup, "encrypt_token", lambda t: b"x")
    await mirror_setup.connect_mirror(OWNER_ID, "123456:" + "A" * 35)
    assert await Alert.all().count() == 0


async def test_ai_without_key_is_reported_from_autoresponder(
    connection, alerts_bot, monkeypatch
):
    from app.features.ai import service as ai
    from app.features.autoresponder import bot as autoresponder
    from app.features.ai.queries import upsert_ai_settings

    await upsert_ai_settings(OWNER_ID, enabled=True)
    monkeypatch.setattr(ai, "is_configured", lambda: False)
    msg = make_message("привет", chat_id=9, from_id=9)
    await autoresponder.handle_incoming(alerts_bot, connection, msg, now=NOW)
    await autoresponder.handle_incoming(alerts_bot, connection, msg, now=NOW + 1)
    assert (await Alert.get(code="ai_no_key")).kind == "state"
    assert len([m for m in alerts_bot.sent if m.get("reply_markup")]) == 1


# --- API ------------------------------------------------------------------------------------
async def test_api_list_dismiss_mute_unmute(client):
    h = client.owner
    await report(OWNER_ID, "no_delete_right", name="A")
    alert = (await client.get("/api/alerts", headers=h)).json()["alerts"][0]
    assert alert["kind"] == "event" and alert["count"] == 1

    r = await client.post(f"/api/alerts/{alert['id']}/dismiss", headers=h)
    assert r.json() == {"dismissed": True}
    assert (await client.get("/api/alerts", headers=h)).json()["alerts"] == []

    await report(OWNER_ID, "command_failed:dice", name="dice")
    alert = (await client.get("/api/alerts", headers=h)).json()["alerts"][0]
    r = await client.post(f"/api/alerts/{alert['id']}/mute", headers=h)
    assert r.json() == {"muted": "command_failed:dice"}
    body = (await client.get("/api/alerts", headers=h)).json()
    assert body == {"alerts": [], "muted": ["command_failed:dice"]}

    r = await client.delete("/api/alerts/mutes/command_failed:dice", headers=h)
    assert r.json() == {"unmuted": True}
    assert (
        await client.delete("/api/alerts/mutes/command_failed:dice", headers=h)
    ).status_code == 404


async def test_api_404_and_isolation(client):
    await report(OWNER_ID, "no_delete_right", name="A")
    alert_id = (await Alert.get(code="no_delete_right")).id
    other = init_data_headers(user_id=777)
    assert (
        await client.post(f"/api/alerts/{alert_id}/mute", headers=other)
    ).status_code == 404
    assert (
        await client.post("/api/alerts/99999/dismiss", headers=client.owner)
    ).status_code == 404
    assert (await client.get("/api/alerts", headers=other)).json() == {
        "alerts": [],
        "muted": [],
    }


async def test_home_counts_active_alerts(client):
    await report(OWNER_ID, "no_delete_right", name="A")
    home = (await client.get("/api/home", headers=client.owner)).json()
    assert home["alerts_active"] == 1
