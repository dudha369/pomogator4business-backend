"""Регрессии чата «Баги B» (HANDOFF_audit, раздел 2, пп. 12–14, 16–27)."""

import asyncio
import types
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)

from db.models.archive_prefs import save_archive_prefs_data
from db.models.autoresponder import add_keyword_reply, list_keyword_replies
from db.models.connection import get_connection, set_prefix
from db.models.emoji_status import (
    is_emoji_status_granted,
    set_emoji_status_enabled,
    set_emoji_status_granted,
)
from db.models.message_history import (
    count_by_chat,
    count_by_day,
    get_history_entry,
    last_rows_by_chat,
    list_history_rows_since,
    save_history,
)
from db.models.message_log import log_message, recent_message_log, trim_message_log
from db.models.module_settings import (
    disable_module,
    enable_module,
    list_disabled_modules,
)
from db.models.quick_template import count_templates
from db.models.user_locale import get_timezone_name, get_timezone_offset
from core import scheduler
from app.platform.telegram.context import CommandContext
from db.models.user_locale import effective_offset, is_valid_timezone

from .conftest import CONNECTION_ID, NOW, OWNER_ID, FakeBot, make_message
from app.features.games.service import get_game


def make_ctx(bot, connection, args="", from_id=OWNER_ID, text=".x"):
    msg = make_message(text, chat_id=7, from_id=from_id)
    return CommandContext(bot=bot, message=msg, connection=connection, args=args)


# --- 12. таймзона: IANA-имя учитывает переход на летнее время ------------------
def test_effective_offset_follows_dst():
    winter = datetime(2026, 1, 15, 12, tzinfo=timezone.utc)
    summer = datetime(2026, 7, 15, 12, tzinfo=timezone.utc)
    assert effective_offset("Europe/Kyiv", 999, now=winter) == 120
    assert effective_offset("Europe/Kyiv", 999, now=summer) == 180


def test_effective_offset_falls_back_on_bad_name():
    assert effective_offset(None, 180) == 180
    assert effective_offset("Mars/Base", 90) == 90
    assert not is_valid_timezone("Mars/Base") and is_valid_timezone("Europe/Kyiv")


async def test_timezone_api_name_then_manual_offset(client):
    h = client.owner
    r = await client.post(
        "/api/account/timezone", headers=h, json={"timezone": "Asia/Tokyo"}
    )
    assert r.status_code == 200 and r.json()["timezone"] == "Asia/Tokyo"
    assert r.json()["offset_minutes"] == 540
    # ручной выбор смещения сбрасывает IANA-имя
    r = await client.post(
        "/api/account/timezone", headers=h, json={"offset_minutes": 60}
    )
    assert r.json() == {"offset_minutes": 60, "timezone": None}
    assert await get_timezone_offset(OWNER_ID) == 60


async def test_timezone_api_rejects_garbage(client):
    h = client.owner
    bad = await client.post(
        "/api/account/timezone", headers=h, json={"timezone": "Nope/Zone"}
    )
    assert bad.status_code == 400
    empty = await client.post("/api/account/timezone", headers=h, json={})
    assert empty.status_code == 422
    far = await client.post(
        "/api/account/timezone", headers=h, json={"offset_minutes": 5000}
    )
    assert far.status_code == 400


async def test_backup_import_applies_iana_timezone(client):
    h = client.owner
    r = await client.post(
        "/api/backup/import", headers=h, json={"version": 1, "timezone": "Europe/Kyiv"}
    )
    assert r.status_code == 200
    assert await get_timezone_name(OWNER_ID) == "Europe/Kyiv"


# --- 13. эмодзи-часы: сеть не отключает, отозванный доступ — отключает --------------
def _network_error():
    return TelegramNetworkError(method=MagicMock(), message="Connection reset by peer")


def _bad_request(text):
    return TelegramBadRequest(method=MagicMock(), message=text)


class ClockBot(FakeBot):
    def __init__(self, error=None):
        super().__init__()
        self.error = error
        self.pushed = []

    async def set_user_emoji_status(self, **kwargs):
        if self.error:
            raise self.error
        self.pushed.append(kwargs)


@pytest.fixture
async def clock_on(database, monkeypatch):
    async def fake_id(cache, time_key, style):
        return "emoji-1"

    monkeypatch.setattr(scheduler, "_emoji_id_for", fake_id)
    await set_emoji_status_granted(OWNER_ID, True)
    await set_emoji_status_enabled(OWNER_ID, True)


async def _push(bot):
    await scheduler._push_emoji_status(bot, OWNER_ID, "x", "12:00", {})


async def test_clock_network_error_keeps_clock_enabled(clock_on):
    bot = ClockBot(_network_error())
    await _push(bot)
    assert await is_emoji_status_granted(OWNER_ID) is True
    assert bot.sent == []  # владельцу тоже ничего не шлём


async def test_clock_unrelated_bad_request_keeps_clock_enabled(clock_on):
    await _push(ClockBot(_bad_request("Bad Request: DOCUMENT_INVALID")))
    assert await is_emoji_status_granted(OWNER_ID) is True


async def test_clock_revoked_access_disables_and_notifies(clock_on):
    bot = ClockBot(_bad_request("Bad Request: user did not grant permission"))
    await _push(bot)
    assert await is_emoji_status_granted(OWNER_ID) is False
    assert len(bot.sent) == 1 and bot.sent[0]["chat_id"] == OWNER_ID


async def test_clock_forbidden_disables(clock_on):
    await _push(
        ClockBot(TelegramForbiddenError(method=MagicMock(), message="Forbidden"))
    )
    assert await is_emoji_status_granted(OWNER_ID) is False


async def test_clock_success_pushes_emoji(clock_on):
    bot = ClockBot()
    await _push(bot)
    assert bot.pushed == [
        {"user_id": OWNER_ID, "emoji_status_custom_emoji_id": "emoji-1"}
    ]


# --- 14. логи не содержат текст личных сообщений ------------------------------
async def test_update_logging_hides_message_text(caplog):
    from app.platform.telegram.middleware import _size

    assert _size("секретное сообщение") == 19 and _size(None) == 0
    import inspect

    from app.platform.telegram import middleware as logging_middleware

    assert "_short" not in inspect.getsource(logging_middleware)


# --- 16. импорт бэкапа соблюдает квоты ------------------------------------------
async def test_backup_import_respects_quotas(client):
    from api.autoresponder import MAX_KEYWORDS
    from api.templates import MAX_TEMPLATES

    h = client.owner
    payload = {
        "version": 1,
        "keywords": [
            {"keyword": f"k{i}", "reply_text": "ответ"}
            for i in range(MAX_KEYWORDS + 20)
        ],
        "templates": [
            {"name": f"t{i}", "text": "x"} for i in range(MAX_TEMPLATES + 10)
        ],
    }
    r = await client.post("/api/backup/import", headers=h, json=payload)
    assert r.status_code == 200
    assert len(await list_keyword_replies(OWNER_ID)) == MAX_KEYWORDS
    assert await count_templates(OWNER_ID) == MAX_TEMPLATES
    assert r.json()["skipped"] >= 30


async def test_backup_import_existing_keyword_is_replaced_at_quota(client):
    from api.autoresponder import MAX_KEYWORDS

    h = client.owner
    for i in range(MAX_KEYWORDS):
        await add_keyword_reply(OWNER_ID, f"k{i}", "old")
    r = await client.post(
        "/api/backup/import",
        headers=h,
        json={"version": 1, "keywords": [{"keyword": "k0", "reply_text": "new"}]},
    )
    assert r.status_code == 200
    rows = {
        k["keyword"]: k["reply_text"] for k in await list_keyword_replies(OWNER_ID)
    }
    assert rows["k0"] == "new" and len(rows) == MAX_KEYWORDS


# --- 17. .calc: память не съедается --------------------------------------------
@pytest.mark.parametrize(
    "expr",
    [
        "((9**999)**999)**999",
        "9**9**9",
        "1" * 300,
        "(" * 150 + "1" + ")" * 150,
        "10**1000 * 10**1000",
    ],
)
def test_calc_rejects_huge_expressions(expr):
    from modules.calc import CalcError, safe_eval

    with pytest.raises(
        (CalcError, SyntaxError, ValueError, OverflowError, RecursionError)
    ):
        safe_eval(expr)


def test_calc_still_works():
    from modules.calc import safe_eval

    assert safe_eval("2**10 + 3*4") == 1036
    assert safe_eval("10/4") == 2.5


# --- 18. шашки: дамка посреди боя, турецкий удар -----------------------------------
def _board(pieces):
    cells = ["."] * 64
    for idx, piece in pieces.items():
        cells[idx] = piece
    return "".join(cells)


def test_checkers_man_promoted_mid_capture_continues_as_king():
    from modules import checkers as c

    # белая шашка (2,1) бьёт (1,2) и встаёт на (0,3) — последняя горизонталь;
    # как дамка она бьёт дальше по диагонали через (2,5) на (3,6)
    board = _board({17: "w", 10: "b", 21: "b"})
    after = c.maybe_promote(c.apply_single_move(board, 17, 3, 10), 3)
    assert after[3] == "W"
    assert any(mid == 21 for _land, mid in c.piece_captures(after, 3))


def test_checkers_captured_piece_blocks_until_series_ends():
    from modules import checkers as c

    board = _board({56: "W", 35: "b", 49: "b"})
    after = c.apply_single_move(board, 56, 28, 35)
    assert after[35] == "x"  # сбитая шашка остаётся на доске
    # через неё нельзя пройти и перепрыгнуть повторно
    assert all(mid != 35 for _land, mid in c.piece_captures(after, 28))
    assert c.finish_series(after)[35] == "."


def test_checkers_captured_marker_is_rendered():
    from modules import checkers as c

    assert "x" in c._SYMBOLS


# --- 19. сапёр ------------------------------------------------------------------
def test_minesweeper_first_click_mine_is_relocated():
    from modules.minesweeper import relocate_mine

    mines = {0, 1, 2}
    moved = relocate_mine(4, mines, 1)
    assert 1 not in moved and len(moved) == 3 and {0, 2} <= moved


def _button_texts(markup):
    return [b.text for row in markup.inline_keyboard for b in row]


def test_minesweeper_flags_after_loss():
    from modules import minesweeper as ms

    keyboard = ms._game_keyboard("ru", 3, {0, 1}, {4}, {0, 8}, None, True, False)
    texts = _button_texts(keyboard)
    assert texts[0] == "🚩"  # верный флаг на мине не рисуется бомбой
    assert texts[8] == "❌"  # ошибочный флаг
    assert texts[1] == "💣"  # нетронутая мина


# --- замок на текстовые ходы игр --------------------------------------------------
async def test_serialized_command_does_not_overlap(connection):
    from app.features.games.lock import serialized_command

    log = []

    @serialized_command
    async def handler(ctx):
        log.append(("in", ctx.n))
        await asyncio.sleep(0.02)
        log.append(("out", ctx.n))

    def ctx(n):
        return types.SimpleNamespace(connection_id=CONNECTION_ID, chat_id=7, n=n)

    await asyncio.gather(handler(ctx(1)), handler(ctx(2)))
    assert log in (
        [("in", 1), ("out", 1), ("in", 2), ("out", 2)],
        [("in", 2), ("out", 2), ("in", 1), ("out", 1)],
    )


async def test_hangman_fast_double_guess_keeps_both_letters(connection):
    from modules.hangman import cmd_hangman

    bot = FakeBot()
    import json

    await cmd_hangman(make_ctx(bot, connection, "ЛАМПА"))
    await asyncio.gather(
        cmd_hangman(make_ctx(bot, connection, "л")),
        cmd_hangman(make_ctx(bot, connection, "м")),
    )
    game = await get_game("hangman", CONNECTION_ID, 7)
    assert {"Л", "М"} <= set(json.loads(game["guessed_letters"]))


# --- 22. ctx.present --------------------------------------------------------------
async def test_present_owner_edits_command_message(connection):
    bot = FakeBot()
    ctx = make_ctx(bot, connection, from_id=OWNER_ID)
    msg_id = await ctx.present("игра")
    assert msg_id == ctx.message.message_id
    assert bot.edited[-1]["text"] == "игра" and not bot.sent


async def test_present_guest_with_right_deletes_command_and_sends(connection):
    bot = FakeBot()
    conn = {**connection, "rights_json": '{"can_delete_all_messages": true}'}
    ctx = make_ctx(bot, conn, from_id=7)
    msg_id = await ctx.present("игра")
    assert bot.deleted and bot.deleted[-1]["message_ids"] == [ctx.message.message_id]
    assert "reply_parameters" not in bot.sent[-1]
    assert msg_id != ctx.message.message_id


async def test_present_guest_without_right_replies_to_command(connection):
    bot = FakeBot()
    ctx = make_ctx(bot, connection, from_id=7)
    await ctx.present("игра")
    assert not bot.deleted and not bot.edited
    assert bot.sent[-1]["reply_parameters"].message_id == ctx.message.message_id


async def test_present_guest_falls_back_when_delete_fails(connection):
    class NoDelete(FakeBot):
        async def delete_business_messages(self, **kw):
            raise RuntimeError("no rights")

    bot = NoDelete()
    conn = {**connection, "rights_json": '{"can_delete_all_messages": true}'}
    ctx = make_ctx(bot, conn, from_id=7)
    await ctx.present("игра")
    assert bot.sent[-1]["reply_parameters"].message_id == ctx.message.message_id


async def test_present_owner_falls_back_to_reply_if_edit_fails(connection):
    class NoEdit(FakeBot):
        async def edit_message_text(self, **kw):
            raise RuntimeError("cannot edit")

    bot = NoEdit()
    await make_ctx(bot, connection, from_id=OWNER_ID).present("игра")
    assert bot.sent[-1]["text"] == "игра"


async def test_ttt_callback_answered_once(connection):
    from modules.ttt import on_ttt_callback

    from .test_games import BORIS, Call, start_ttt

    bot = FakeBot()
    await start_ttt(bot, connection)
    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    stranger = Call("ttt:0", 999, "Чужой")
    await on_ttt_callback(stranger, bot)
    assert len(stranger.answers) == 1  # alert «не ваша игра», без второго answer()


# --- 22. правки: бот, свои сообщения -----------------------------------------------
async def test_bot_edit_marker_marks_and_expires(monkeypatch):
    from aiogram.methods import EditMessageText

    from core import self_actions as sa

    sa._bot_edits.clear()
    called = []

    async def make_request(bot, method):
        called.append(method)
        return "ok"

    method = EditMessageText(
        business_connection_id=CONNECTION_ID, chat_id=7, message_id=55, text="x"
    )
    assert await sa.BotEditMarker()(make_request, None, method) == "ok" and called
    assert sa.is_bot_edit(CONNECTION_ID, 7, 55)
    assert not sa.is_bot_edit(CONNECTION_ID, 7, 56)
    sa._bot_edits[(CONNECTION_ID, 7, 55)] = 0  # срок вышел
    assert not sa.is_bot_edit(CONNECTION_ID, 7, 55)


async def test_bot_edit_marker_ignores_non_business_edits():
    from aiogram.methods import EditMessageText

    from core import self_actions as sa

    sa._bot_edits.clear()

    async def make_request(bot, method):
        return None

    plain = EditMessageText(chat_id=OWNER_ID, message_id=9, text="x")
    await sa.BotEditMarker()(make_request, None, plain)
    assert sa._bot_edits == {}


def test_own_edits_pref_defaults_off_and_is_patchable():
    from core.archive_prefs import defaults, validate_patch

    assert defaults().own_edits is False
    assert validate_patch({"own_edits": True})["own_edits"] is True


async def _own_message(bot, text):
    from handlers.business_messages import on_business_message

    await disable_module(CONNECTION_ID, "scam")
    msg = make_message(text, chat_id=7, from_id=OWNER_ID)
    await on_business_message(msg, bot)
    return msg


async def _edit_own(bot, msg, text):
    from modules.archive import on_business_edited

    edited = make_message(text, chat_id=7, from_id=OWNER_ID)
    edited.message_id = msg.message_id
    await on_business_edited(edited, bot)


async def test_own_edit_is_silent_by_default(connection):
    bot = FakeBot()
    msg = await _own_message(bot, "было")
    await _edit_own(bot, msg, "стало")
    assert bot.sent == [] and bot.edited == []


async def test_own_edit_notifies_when_enabled_and_marks_owner(connection):
    from db.models.archive_log import ArchiveLog

    await save_archive_prefs_data(CONNECTION_ID, {"own_edits": True})
    bot = FakeBot()
    msg = await _own_message(bot, "было")
    await _edit_own(bot, msg, "стало")
    assert bot.sent or getattr(bot, "rich_sent", None)
    rows = await ArchiveLog.filter(event="edited").values("is_owner")
    assert rows and rows[0]["is_owner"] is True


async def test_bot_edit_is_not_reported_even_when_own_edits_enabled(connection):
    from core import self_actions as sa

    await save_archive_prefs_data(CONNECTION_ID, {"own_edits": True})
    bot = FakeBot()
    msg = await _own_message(bot, "было")
    sa._mark_bot_edit(CONNECTION_ID, 7, msg.message_id)
    await _edit_own(bot, msg, "стало")
    assert bot.sent == []
    # история при этом актуальна
    entry = await get_history_entry(CONNECTION_ID, 7, msg.message_id)
    assert entry["text"] == "стало"


# --- 21. сбой команды не проходит молча -----------------------------------------------
async def test_command_failure_is_reported_once_per_minute(connection):
    from handlers import business_messages as bm

    bm._last_failure_notice.clear()
    bot = FakeBot()
    inc = types.SimpleNamespace(
        bot=bot, connection=connection, connection_id=CONNECTION_ID
    )
    await bm._report_command_failure(inc, "dice", "ru")
    await bm._report_command_failure(inc, "dice", "ru")
    await bm._report_command_failure(inc, "flip", "ru")
    assert [m["chat_id"] for m in bot.sent] == [OWNER_ID, OWNER_ID]
    assert ".dice" in bot.sent[0]["text"]


# --- 23. нагрузка на БД ------------------------------------------------------------
async def _seed_history():
    rows = [
        (7, 1, False, NOW),
        (7, 2, True, NOW + 60),
        (7, 3, False, NOW + 120),
        (8, 1, False, NOW + 30),
        (8, 2, True, NOW - 2 * 86400),
    ]
    for chat_id, message_id, is_owner, ts in rows:
        await save_history(CONNECTION_ID, chat_id, message_id, is_owner, "t", ts)


async def test_sql_aggregates_match_python(connection):
    from core import stats

    await _seed_history()
    since = NOW - 5 * 86400
    by_day = await count_by_day(CONNECTION_ID, since, 0)
    today = NOW // 86400
    day_rows = {(int(r["day"]), bool(r["is_owner"])): int(r["n"]) for r in by_day}
    assert day_rows[(today, False)] == 3 and day_rows[(today, True)] == 1
    assert day_rows[(today - 2, True)] == 1

    py = stats.daily_activity(
        await list_history_rows_since(CONNECTION_ID, since), NOW, 0, 5
    )
    sql = stats.daily_from_counts(by_day, NOW, 0, 5)
    assert py == sql

    top = stats.top_from_counts(await count_by_chat(CONNECTION_ID, since))
    assert top[0] == {"chat_id": 7, "incoming": 2, "outgoing": 1}


async def test_last_rows_by_chat_picks_latest_message(connection):
    await _seed_history()
    rows = {
        r["chat_id"]: r
        for r in await last_rows_by_chat(CONNECTION_ID, NOW - 5 * 86400)
    }
    assert rows[7]["message_id"] == 3 and not rows[7]["is_owner"]
    assert (
        rows[8]["message_id"] == 1 and not rows[8]["is_owner"]
    )  # входящее новее ответа


async def test_message_log_only_for_owner_messages(connection):
    from handlers.business_messages import on_business_message

    await disable_module(CONNECTION_ID, "scam")
    bot = FakeBot()
    await on_business_message(make_message("от собеседника", chat_id=7, from_id=7), bot)
    assert await recent_message_log(CONNECTION_ID, 7, 10) == []
    mine = make_message("от меня", chat_id=7, from_id=OWNER_ID)
    await on_business_message(mine, bot)
    assert [m for _log, m in await recent_message_log(CONNECTION_ID, 7, 10)] == [
        mine.message_id
    ]


async def test_trim_message_log_is_per_connection(database):
    for conn in ("a", "b"):
        for message_id in range(5):
            await log_message(conn, 1, message_id)
    await log_message("b", 1, 99)
    removed = await trim_message_log(2)
    assert removed == 3 + 4
    for conn, expected in (("a", [3, 4]), ("b", [4, 99])):
        got = sorted(m for _l, m in await recent_message_log(conn, 1, 10))
        assert got == expected


def test_raw_json_kept_only_for_exotic_kinds(monkeypatch):
    from core import snapshot

    def fake(kind):
        return lambda message, bot_id=None: {"kind": kind, "raw_json": {"a": 1}}

    monkeypatch.setattr(snapshot, "_build_snapshot", fake("text"))
    assert snapshot.build_snapshot(None)["raw_json"] is None
    monkeypatch.setattr(snapshot, "_build_snapshot", fake("photo"))
    assert snapshot.build_snapshot(None)["raw_json"] is None
    monkeypatch.setattr(snapshot, "_build_snapshot", fake("dice"))
    assert snapshot.build_snapshot(None)["raw_json"] == {"a": 1}


async def test_ttl_cache_is_invalidated_on_writes(connection):
    first = await get_connection(CONNECTION_ID)
    assert first["prefix"] == "."
    await set_prefix(CONNECTION_ID, "!")
    assert (await get_connection(CONNECTION_ID))["prefix"] == "!"

    assert await list_disabled_modules(CONNECTION_ID) == set()
    await disable_module(CONNECTION_ID, "calc")
    assert await list_disabled_modules(CONNECTION_ID) == {"calc"}
    await enable_module(CONNECTION_ID, "calc")
    assert await list_disabled_modules(CONNECTION_ID) == set()


async def test_ttl_cache_returns_independent_copies(connection):
    a = await get_connection(CONNECTION_ID)
    a["prefix"] = "ЛОМАЮ"
    assert (await get_connection(CONNECTION_ID))["prefix"] != "ЛОМАЮ"


# --- 24. /readall в фоне ----------------------------------------------------------
async def test_readall_status_idle(client):
    from api import chats

    chats._jobs.clear()
    r = await client.get("/api/readall/status", headers=client.owner)
    assert r.json() == {"running": False, "matched": 0, "done": 0, "failed": 0}


async def test_readall_returns_progress_when_slow(client, api_bot, monkeypatch):
    from api import chats

    await _seed_history()
    monkeypatch.setattr(chats, "_WAIT_SECONDS", 0.05)
    gate = asyncio.Event()
    import bot_instance

    original = bot_instance.bot.read_business_message

    async def slow(**kw):
        await gate.wait()
        await original(**kw)

    monkeypatch.setattr(bot_instance.bot, "read_business_message", slow)
    chats._jobs.clear()
    r = await client.post("/api/readall", headers=client.owner, json={})
    assert r.json()["running"] is True and r.json()["matched"] == 2
    gate.set()
    for _ in range(50):
        status = (await client.get("/api/readall/status", headers=client.owner)).json()
        if not status["running"]:
            break
        await asyncio.sleep(0.05)
    assert status == {"running": False, "matched": 2, "done": 2, "failed": 0}


# --- 27. maintenance / allowlist -----------------------------------------------------
async def test_maintenance_mode_returns_503(client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "MAINTENANCE_MODE", True)
    r = await client.get("/api/account", headers=client.owner)
    assert r.status_code == 503 and r.json()["detail"] == {"reason": "maintenance_mode"}


async def test_allowlist_blocks_other_users(client, monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "ALLOWED_USER_IDS", "1, 2")
    r = await client.get("/api/account", headers=client.owner)
    assert r.status_code == 403 and r.json()["detail"] == {"reason": "access_denied"}
    monkeypatch.setattr(settings, "ALLOWED_USER_IDS", f"1,{OWNER_ID}")
    assert (await client.get("/api/account", headers=client.owner)).status_code == 200


# --- 20. мелочи ---------------------------------------------------------------------
def test_city_skips_yery_and_split_has_words_alias():
    from app.platform.telegram.registry import registry
    from modules import city

    assert "Ы" in city._SKIP_LETTERS
    assert registry.find("words") is not None


async def test_qr_too_long_text_is_rejected_politely(connection):
    from modules.qr import cmd_qr

    bot = FakeBot()
    await cmd_qr(make_ctx(bot, connection, "я" * 5000))
    assert bot.sent  # usage_error вместо падения
