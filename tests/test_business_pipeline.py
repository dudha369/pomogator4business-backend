"""Цепочка middleware бизнес-сообщений (Арх.4): порядок шагов, остановка цепочки,
поведение каждого перенесённого шага и слои фичи history."""

import ast
import types
from pathlib import Path

import pytest

from app.features.echo.queries import toggle_echo
from app.features.history.service import get_history_entry
from app.platform.telegram.pipeline import STEPS, build_router, router
from app.platform.telegram.registry import registry
from db.models.module_settings import disable_module

from .conftest import (
    CONNECTION_ID,
    OWNER_ID,
    make_message,
    on_business_message,
)

CHAT = 7
ROOT = Path(__file__).resolve().parent.parent


def _names(funcs):
    return [f.__name__ for f in funcs]


# --- порядок -----------------------------------------------------------------------
def test_steps_order_is_preserved():
    assert _names(STEPS) == [
        "owner_journal",
        "rescue_replied_media",  # спасение — до записи самого сообщения
        "record_history",
        "voice_transcript",  # после записи: дописывает текст в сохранённую строку
        "voice_step",
        "new_contact_step",
        "mute_gate",
        "autoresponder_step",
        "echo_step",
        "type_trigger_step",
    ]


def test_router_registers_steps_in_that_order():
    r = build_router()
    obs = r.business_message
    assert _names(obs.outer_middleware) == ["load_incoming"]
    assert [m.__name__ for m in obs.middleware] == _names(STEPS)
    assert len(obs.handlers) == 1  # диспетчер команд — единственный обработчик


def test_module_level_router_is_the_one_in_bot_instance():
    import bot_instance

    assert router in bot_instance.dp.sub_routers


# --- контекст ----------------------------------------------------------------------
async def test_unknown_connection_stops_chain(database, bot):
    await on_business_message(make_message("hi"), bot)
    assert bot.sent == []


async def test_owner_message_goes_to_message_log(connection, bot):
    from app.features.history.service import recent_message_log

    msg = make_message("привет", chat_id=CHAT, from_id=OWNER_ID)
    await on_business_message(msg, bot)
    rows = await recent_message_log(CONNECTION_ID, CHAT, 10)
    assert msg.message_id in [m for _l, m in rows]


async def test_contact_message_not_in_message_log(connection, bot):
    from app.features.history.service import recent_message_log

    msg = make_message("привет", chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)
    assert await recent_message_log(CONNECTION_ID, CHAT, 10) == []


# --- остановка цепочки ---------------------------------------------------------------
@pytest.fixture
def spy_ping(monkeypatch):
    calls = []

    async def handler(ctx):
        calls.append(ctx)

    monkeypatch.setattr(registry.find("ping"), "handler", handler)
    return calls


async def test_history_saved_even_when_mute_stops_chain(connection, bot, monkeypatch):
    await disable_module(CONNECTION_ID, "scam")

    async def muted(*a):
        return True

    monkeypatch.setattr("app.features.mute.bot.handle_incoming", muted)
    msg = make_message("тихо", chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)
    assert await get_history_entry(CONNECTION_ID, CHAT, msg.message_id) is not None


async def test_mute_disabled_module_does_not_mute(connection, bot, monkeypatch):
    await disable_module(CONNECTION_ID, "scam")
    await disable_module(CONNECTION_ID, "mute")
    called = []

    async def muted(*a):
        called.append(1)
        return True

    monkeypatch.setattr("app.features.mute.bot.handle_incoming", muted)
    await on_business_message(make_message("x", chat_id=CHAT, from_id=CHAT), bot)
    assert called == []


async def test_mute_does_not_apply_to_owner(connection, bot, monkeypatch, spy_ping):
    called = []

    async def muted(*a):
        called.append(1)
        return True

    monkeypatch.setattr("app.features.mute.bot.handle_incoming", muted)
    await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert called == [] and len(spy_ping) == 1


async def test_echo_stops_before_type_trigger_and_commands(
    connection, bot, monkeypatch
):
    await disable_module(CONNECTION_ID, "scam")
    await toggle_echo(CONNECTION_ID, CHAT)
    seen = []

    async def fake_type(*a):
        seen.append(1)

    monkeypatch.setattr("commands.type_.handle_type_trigger", fake_type)
    await on_business_message(make_message("_type x", chat_id=CHAT, from_id=CHAT), bot)
    assert seen == [] and [m["text"] for m in bot.sent] == ["_type x"]


async def test_echo_disabled_module_passes_through(connection, bot):
    await disable_module(CONNECTION_ID, "scam")
    await disable_module(CONNECTION_ID, "echo")
    await toggle_echo(CONNECTION_ID, CHAT)
    await on_business_message(make_message("эхо", chat_id=CHAT, from_id=CHAT), bot)
    assert bot.sent == []


async def test_echo_not_applied_to_owner(connection, bot, spy_ping):
    await toggle_echo(CONNECTION_ID, CHAT)
    await on_business_message(
        make_message(".ping", chat_id=CHAT, from_id=OWNER_ID), bot
    )
    assert len(spy_ping) == 1


async def test_type_trigger_without_module_does_not_reach_command(
    connection, bot, monkeypatch
):
    """Сообщение с триггером всегда заканчивает цепочку — даже если модуль выключен."""
    await disable_module(CONNECTION_ID, "type")
    seen = []

    async def fake_type(*a):
        seen.append(1)

    monkeypatch.setattr("commands.type_.handle_type_trigger", fake_type)
    await on_business_message(make_message("_type hi", from_id=OWNER_ID), bot)
    assert seen == [] and bot.sent == []


async def test_non_trigger_text_reaches_command(connection, bot, spy_ping):
    await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert len(spy_ping) == 1


async def test_textless_message_does_not_crash_dispatch(connection, bot):
    await disable_module(CONNECTION_ID, "scam")
    msg = make_message(None, chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)  # не должно упасть
    assert bot.sent == []


# --- голосовое владельца -----------------------------------------------------------
async def test_voice_step_handled_stops_chain(connection, bot, monkeypatch, spy_ping):
    seen = []

    async def handled(bot_, connection_, message):
        seen.append(1)
        return True

    monkeypatch.setattr("app.features.voice_effects.bot.handle_voice_message", handled)
    msg = make_message(".ping", from_id=OWNER_ID)
    msg.voice = types.SimpleNamespace(file_id="v", duration=3)
    await on_business_message(msg, bot)
    assert seen == [1] and spy_ping == []


async def test_voice_step_not_handled_falls_through_to_command(
    connection, bot, monkeypatch, spy_ping
):
    async def unhandled(*a):
        return False

    monkeypatch.setattr(
        "app.features.voice_effects.bot.handle_voice_message", unhandled
    )
    msg = make_message(".ping", from_id=OWNER_ID)
    msg.voice = types.SimpleNamespace(file_id="v", duration=3)
    await on_business_message(msg, bot)
    assert len(spy_ping) == 1


async def test_voice_step_only_for_owner_and_enabled_module(
    connection, bot, monkeypatch
):
    seen = []

    async def handled(*a):
        seen.append(1)
        return True

    monkeypatch.setattr("app.features.voice_effects.bot.handle_voice_message", handled)
    await disable_module(CONNECTION_ID, "scam")
    contact = make_message("x", chat_id=CHAT, from_id=CHAT)
    contact.voice = types.SimpleNamespace(file_id="v", duration=3)
    await on_business_message(contact, bot)
    await disable_module(CONNECTION_ID, "voice")
    mine = make_message("x", from_id=OWNER_ID)
    mine.voice = types.SimpleNamespace(file_id="v", duration=3)
    await on_business_message(mine, bot)
    assert seen == []


# --- расшифровка голосовых ----------------------------------------------------------
@pytest.fixture
def transcripts(monkeypatch):
    calls = []

    async def fake(bot_, connection_id, chat_id, message_id, voice):
        calls.append(message_id)

    monkeypatch.setattr(
        "app.features.archive.bot.transcript.transcribe_into_history", fake
    )
    return calls


async def _voice(bot, from_id, duration=5, **kw):
    msg = make_message(None, chat_id=CHAT, from_id=from_id)
    msg.voice = types.SimpleNamespace(file_id="v", duration=duration)
    await on_business_message(msg, bot)
    import asyncio

    await asyncio.sleep(0)  # spawn() — фоновая задача
    return msg


async def test_transcript_runs_for_contact_voice_when_pref_on(
    connection, bot, transcripts
):
    from app.features.archive.prefs import load_prefs, update_prefs

    await disable_module(CONNECTION_ID, "scam")
    await update_prefs(CONNECTION_ID, {"voice_transcript": True})
    assert (await load_prefs(CONNECTION_ID)).voice_transcript
    msg = await _voice(bot, CHAT)
    assert transcripts == [msg.message_id]


async def test_transcript_skipped_for_owner_long_voice_and_pref_off(
    connection, bot, transcripts
):
    from app.features.archive.prefs import update_prefs

    await disable_module(CONNECTION_ID, "scam")
    await _voice(bot, CHAT)  # настройка выключена
    await update_prefs(CONNECTION_ID, {"voice_transcript": True})
    await _voice(bot, OWNER_ID)
    await _voice(bot, CHAT, duration=121)
    assert transcripts == []


# --- контакт ----------------------------------------------------------------------
async def test_new_contact_step_runs_scam_check_for_contact_only(
    connection, bot, monkeypatch
):
    seen = []

    async def fake(bot_, connection_, message):
        seen.append(message.from_user.id)

    monkeypatch.setattr("commands.scam.handle_new_contact", fake)
    await on_business_message(make_message("hi", chat_id=CHAT, from_id=CHAT), bot)
    await on_business_message(make_message("hi", chat_id=CHAT, from_id=OWNER_ID), bot)
    assert seen == [CHAT]


# --- команды: недоступно собеседнику, сбой сообщается --------------------------------
async def test_failing_command_notifies_owner_and_chain_ends(
    connection, bot, alerts_bot, monkeypatch
):
    async def boom(ctx):
        raise RuntimeError("x")

    monkeypatch.setattr(registry.find("ping"), "handler", boom)
    await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert bot.sent == []
    assert [m["chat_id"] for m in alerts_bot.sent] == [OWNER_ID]


def test_registry_fallbacks_contain_wordle():
    assert "wordle" in [m for m, _h in registry.fallbacks()]


# --- слои и зависимости ------------------------------------------------------------
def _imports(path: Path) -> set[str]:
    out = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_db_layer_does_not_import_features():
    for path in (ROOT / "db/models").glob("*.py"):
        bad = [m for m in _imports(path) if m.startswith("app.features")]
        assert not bad, (path.name, bad)


def test_history_data_layers_do_not_import_aiogram_or_archive():
    root = ROOT / "app/features/history"
    for name in ("models", "service", "snapshot"):
        mods = _imports(root / f"{name}.py")
        assert not [m for m in mods if m.split(".")[0] == "aiogram"], name
    for path in root.glob("*.py"):
        assert not [
            m for m in _imports(path) if m.startswith("app.features.archive")
        ], path.name


def test_history_feature_registered_without_locales():
    from app.features import FEATURES, feature_module

    assert "history" in FEATURES
    assert feature_module("history", "locales") is None
    assert feature_module("history", "bot") is not None


def test_old_names_are_gone():
    for rel in ("app/platform/telegram/pipeline.py",):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for old in ("PIPELINE", "run_pipeline", "step_history", "Incoming("):
            assert old not in src, old
    assert not (ROOT / "db/models/message_history.py").exists()
    assert not (ROOT / "app/features/archive/adapter.py").exists()


# --- API ---------------------------------------------------------------------------
def test_api_routes_include_every_feature_router():
    from fastapi import FastAPI

    from app.platform.api import setup_routers

    app = FastAPI()
    app.include_router(setup_routers(), prefix="/api")
    paths = {p.removeprefix("/api") for p in app.openapi()["paths"]}
    assert "/archive" in paths and "/archive/export" in paths
    assert any(p.startswith("/templates") for p in paths)
    assert any(p.startswith("/reminders") for p in paths)
