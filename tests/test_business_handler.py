"""Характеризационные тесты обработчика бизнес-сообщений: фиксируют порядок и
результат шагов (история → голос → scam/known → mute → автоответчик → эхо →
type-триггеры → команды). Должны проходить и до, и после рефакторинга."""

import types

import pytest

from core import database as db
from core.registry import registry
from handlers.business_messages import on_business_message

from .conftest import CONNECTION_ID, OWNER_ID, make_message

CHAT = 7


@pytest.fixture
def spy_command(monkeypatch):
    """Подменяет обработчик команды ping и запоминает вызовы."""
    calls = []
    cmd = registry.find("ping")

    async def handler(ctx):
        calls.append(ctx)

    monkeypatch.setattr(cmd, "handler", handler)
    return calls


async def test_owner_message_saved_to_history(connection, bot):
    msg = make_message("привет", chat_id=CHAT, from_id=OWNER_ID)
    await on_business_message(msg, bot)
    entry = await db.get_history_entry(CONNECTION_ID, CHAT, msg.message_id)
    assert entry["text"] == "привет" and entry["is_owner"] is True


async def test_archive_module_disabled_still_saves_text(connection, bot):
    """Выключенный archive отключает только скачивание медиа: текст попадает в
    историю всё равно (она нужна и другим частям бота, например определению
    нового контакта). Если это не задумано — это баг, но пока фиксируем факт."""
    await db.disable_module(CONNECTION_ID, "archive")
    await db.disable_module(CONNECTION_ID, "scam")
    msg = make_message("текст", chat_id=CHAT)
    await on_business_message(msg, bot)
    entry = await db.get_history_entry(CONNECTION_ID, CHAT, msg.message_id)
    assert entry is not None and entry["media_type"] is None


async def test_disabled_connection_ignored(database, bot):
    await db.upsert_connection(CONNECTION_ID, OWNER_ID, OWNER_ID, False)
    await on_business_message(make_message("hi"), bot)
    assert bot.sent == []


async def test_owner_command_dispatched(connection, bot, spy_command):
    await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert len(spy_command) == 1 and spy_command[0].args == ""


async def test_command_with_args_and_custom_prefix(connection, bot, spy_command):
    await db.set_prefix(CONNECTION_ID, "!")
    await on_business_message(make_message("!pong abc def", from_id=OWNER_ID), bot)
    assert spy_command[0].args == "abc def"
    await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert len(spy_command) == 1  # со старым префиксом — не команда


async def test_owner_only_command_ignored_for_contact(connection, bot, spy_command):
    await on_business_message(make_message(".ping", from_id=CHAT), bot)
    assert spy_command == []


async def test_disabled_module_blocks_command(connection, bot, spy_command):
    await db.disable_module(CONNECTION_ID, "ping")
    await on_business_message(make_message(".ping", from_id=OWNER_ID), bot)
    assert spy_command == []


async def test_user_alias_resolves_to_command(connection, bot, spy_command):
    await db.add_command_alias(OWNER_ID, "пп", "ping")
    await on_business_message(make_message(".пп", from_id=OWNER_ID), bot)
    assert len(spy_command) == 1


async def test_unknown_command_goes_to_wordle(connection, bot, monkeypatch):
    seen = []

    async def fake_guess(bot_, connection_, message, locale, alias):
        seen.append(alias)

    monkeypatch.setattr("handlers.business_messages.handle_wordle_guess", fake_guess)
    await on_business_message(make_message(".слово", from_id=OWNER_ID), bot)
    assert seen == ["слово"]
    await db.disable_module(CONNECTION_ID, "wordle")
    await on_business_message(make_message(".слово", from_id=OWNER_ID), bot)
    assert seen == ["слово"]  # модуль выключен — угадывание не вызывается


async def test_type_trigger(connection, bot, monkeypatch):
    seen = []

    async def fake_type(bot_, message, connection_, trigger):
        seen.append(trigger)

    monkeypatch.setattr("handlers.business_messages.handle_type_trigger", fake_type)
    await on_business_message(make_message("_type hello", from_id=OWNER_ID), bot)
    await on_business_message(
        make_message("_type hello", from_id=CHAT), bot
    )  # не владелец
    assert seen == ["_type"]


async def test_contact_marked_known_even_with_scam_disabled(connection, bot):
    await db.disable_module(CONNECTION_ID, "scam")
    await on_business_message(make_message("привет", chat_id=CHAT, from_id=CHAT), bot)
    assert await db.is_known_chat(OWNER_ID, CHAT)


async def test_autoresponder_greets_new_contact(connection, bot):
    await db.disable_module(CONNECTION_ID, "scam")
    await db.upsert_autoresponder_settings(
        OWNER_ID, greeting_enabled=True, greeting_text="Привет, {name}!"
    )
    await on_business_message(
        make_message("здравствуйте", chat_id=CHAT, from_id=CHAT), bot
    )
    assert [m["text"] for m in bot.sent] == ["Привет, Аня!"]
    await on_business_message(make_message("ещё", chat_id=CHAT, from_id=CHAT), bot)
    assert len(bot.sent) == 1  # приветствие — один раз


async def test_autoresponder_failure_does_not_break_pipeline(
    connection, bot, monkeypatch
):
    await db.disable_module(CONNECTION_ID, "scam")

    async def boom(*a, **k):
        raise RuntimeError("boom")

    monkeypatch.setattr("handlers.business_messages.handle_autoresponder", boom)
    msg = make_message("привет", chat_id=CHAT, from_id=CHAT)
    await on_business_message(msg, bot)  # не должно упасть
    assert await db.get_history_entry(CONNECTION_ID, CHAT, msg.message_id) is not None


async def test_mute_stops_autoresponder(connection, bot, monkeypatch):
    await db.disable_module(CONNECTION_ID, "scam")
    await db.upsert_autoresponder_settings(
        OWNER_ID, greeting_enabled=True, greeting_text="Привет!"
    )

    async def muted(bot_, connection_, message):
        return True

    monkeypatch.setattr("handlers.business_messages.handle_mute_incoming", muted)
    await on_business_message(make_message("привет", chat_id=CHAT, from_id=CHAT), bot)
    assert bot.sent == []


async def test_echo_repeats_contact_text(connection, bot):
    await db.disable_module(CONNECTION_ID, "scam")
    await db.toggle_echo(CONNECTION_ID, CHAT)
    await on_business_message(make_message("эхо", chat_id=CHAT, from_id=CHAT), bot)
    assert [m["text"] for m in bot.sent] == ["эхо"]


async def test_echo_does_not_run_commands(connection, bot, spy_command):
    await db.disable_module(CONNECTION_ID, "scam")
    await db.toggle_echo(CONNECTION_ID, CHAT)
    await on_business_message(make_message(".ping", chat_id=CHAT, from_id=CHAT), bot)
    assert spy_command == []
