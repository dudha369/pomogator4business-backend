import types

import pytest

from core import autoresponder as ar
from core import database as db
from core.retention import run_retention_once

from .conftest import CONNECTION_ID, NOW, OWNER_ID, make_message

DAY = NOW - (NOW % 86400)  # полночь UTC
NOON = DAY + 12 * 3600


def at(hour, minute=0):
    return DAY + hour * 3600 + minute * 60


# ----------------------------- чистая логика --------------------------------


def test_away_window_across_midnight():
    f = ar.in_away_window
    assert f(at(23), 0, 22 * 60, 8 * 60) and f(at(3), 0, 22 * 60, 8 * 60)
    assert not f(at(12), 0, 22 * 60, 8 * 60)
    assert f(at(10), 0, 9 * 60, 18 * 60) and not f(at(18), 0, 9 * 60, 18 * 60)


def test_away_window_without_schedule_is_always_on():
    assert ar.in_away_window(at(12), 0, None, None)
    assert ar.in_away_window(at(12), 0, 600, 600)


def test_away_window_respects_timezone():
    assert ar.in_away_window(at(21), 180, 22 * 60, 8 * 60)  # 00:00 в UTC+3
    assert ar.in_away_window(at(12), -300, 22 * 60, 8 * 60)  # 07:00 в UTC-5
    assert not ar.in_away_window(at(14), -300, 22 * 60, 8 * 60)  # 09:00


def test_keyword_longest_match_wins():
    kw = [
        {"keyword": "цена", "reply_text": "a"},
        {"keyword": "цена доставки", "reply_text": "b"},
    ]
    assert ar.pick_keyword("Какая ЦЕНА доставки?", kw)["reply_text"] == "b"
    assert ar.pick_keyword("привет", kw) is None


def test_render_keeps_unknown_braces():
    user = types.SimpleNamespace(first_name="Аня", full_name="Аня К")
    assert ar.render("{name}|{first_name}|{full_name}|{x}", user) == "Аня|Аня|Аня К|{x}"


# ------------------------------ сценарии ------------------------------------


@pytest.fixture
async def configured(connection):
    await db.set_timezone_offset(OWNER_ID, 0)  # тесты считают время в UTC
    await db.upsert_autoresponder_settings(
        OWNER_ID,
        greeting_enabled=True,
        greeting_text="Привет, {name}!",
        away_enabled=True,
        away_text="Я не на месте",
        away_start_minutes=22 * 60,
        away_end_minutes=8 * 60,
    )
    await db.add_keyword_reply(OWNER_ID, "цена", "Прайс: 100")
    return connection


async def deliver(connection, bot, text, chat=7, now=NOON, **kw):
    msg = make_message(text, chat_id=chat, from_id=kw.pop("from_id", chat), **kw)
    await db.save_history(CONNECTION_ID, chat, msg.message_id, False, text, now)
    reply = await ar.handle_incoming(bot, connection, msg, now=now)
    return reply.kind if reply else None


async def test_no_settings_no_reply(connection, bot):
    assert await deliver(connection, bot, "hi") is None
    assert bot.sent == []


async def test_greeting_once(configured, bot):
    assert await deliver(configured, bot, "привет") == "greeting"
    assert bot.sent[-1]["text"] == "Привет, Аня!"
    assert await deliver(configured, bot, "ещё", now=NOON + 60) is None


async def test_keyword_cooldown(configured, bot):
    await deliver(configured, bot, "привет")
    assert await deliver(configured, bot, "Какая ЦЕНА?", now=NOON + 120) == "keyword"
    assert await deliver(configured, bot, "цена?", now=NOON + 200) is None
    assert await deliver(configured, bot, "цена?", now=NOON + 120 + 301) == "keyword"


async def test_new_contact_with_keyword_is_not_greeted_later(configured, bot):
    assert await deliver(configured, bot, "цена?", chat=8) == "keyword"
    assert await deliver(configured, bot, "ок", chat=8, now=NOON + 10) is None


async def test_away_wins_over_greeting_and_has_cooldown(configured, bot):
    night = at(23)
    assert await deliver(configured, bot, "здрасте", chat=9, now=night) == "away"
    assert await deliver(configured, bot, "?", chat=9, now=night + 60) is None
    assert await db.last_autoreply_at(OWNER_ID, 9, "greeting") is not None
    assert (
        await deliver(configured, bot, "?", chat=9, now=night + 6 * 3600 + 1) == "away"
    )


async def test_away_silent_when_owner_recently_wrote(configured, bot):
    night = at(23)
    await db.save_history(CONNECTION_ID, 10, 900, True, "я тут", night - 60)
    assert await deliver(configured, bot, "алло", chat=10, now=night) is None


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": ".ping"},
        {"text": "hi", "is_bot": True},
        {"text": "hi", "chat_type": "supergroup"},
    ],
)
async def test_ignores_commands_bots_and_groups(configured, bot, kwargs):
    msg = make_message(chat_id=11, from_id=11, **kwargs)
    assert await ar.handle_incoming(bot, configured, msg, now=NOON) is None
    assert bot.sent == []


async def test_failed_send_is_not_logged(configured, bot, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("network")

    monkeypatch.setattr(bot, "send_message", boom)
    assert await deliver(configured, bot, "hi", chat=14) is None
    assert await db.last_autoreply_at(OWNER_ID, 14, "greeting") is None


async def test_auto_read_skips_favorites(configured, bot):
    await db.upsert_autoresponder_settings(
        OWNER_ID, auto_read_enabled=True, greeting_enabled=False, away_enabled=False
    )
    await db.set_favorite_chat(OWNER_ID, 16, True)
    await deliver(configured, bot, "x", chat=15)
    await deliver(configured, bot, "x", chat=16)
    assert [r["chat_id"] for r in bot.reads] == [15]


async def test_retention_keeps_greeting_ledger(configured):
    await db.log_autoreply(OWNER_ID, 99, "keyword", "k", NOW - 40 * 86400)
    await db.log_autoreply(OWNER_ID, 99, "greeting", None, NOW - 400 * 86400)
    stats = await run_retention_once(NOW)
    assert stats["autoresponder_log_purged"] == 1
    assert await db.last_autoreply_at(OWNER_ID, 99, "greeting") is not None
