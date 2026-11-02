"""Крестики-нолики и шашки: игровой цикл, id вместо имён в БД, упоминания в тексте."""

import types

import pytest

from core import database as db
from core import mentions
from modules.checkers import cmd_chk, on_chk_callback
from modules.ttt import cmd_ttt, on_ttt_callback

from .conftest import CONNECTION_ID, FakeBot, make_message

CHAT = 7
ANYA, BORIS = 7, 8
# id сообщения, в котором «живёт» последняя запущенная игра (как в Telegram,
# где кнопки принадлежат конкретному сообщению)
_LAST = {"message_id": 500}


@pytest.fixture(autouse=True)
def clean_mentions():
    mentions.clear_cache()
    yield
    mentions.clear_cache()


class Call:
    """Нажатие inline-кнопки."""

    def __init__(self, data, user_id, name, username=None, message_id=None):
        self.data = data
        self.from_user = types.SimpleNamespace(
            id=user_id, full_name=name, username=username
        )
        self.edits, self.answers = [], []
        self.message = types.SimpleNamespace(
            business_connection_id=CONNECTION_ID,
            chat=types.SimpleNamespace(id=CHAT),
            message_id=message_id or _LAST["message_id"],
            edit_text=self._edit,
            edit_reply_markup=self._noop,
        )

    async def _edit(self, text, reply_markup=None, parse_mode=None, **kw):
        self.edits.append(
            {"text": text, "markup": reply_markup, "parse_mode": parse_mode}
        )

    async def _noop(self, **kw):
        pass

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


def command_ctx(bot, connection, user_id, name, username=None):
    from core.context import CommandContext

    msg = make_message("." + "x", chat_id=CHAT, from_id=user_id)
    msg.from_user = types.SimpleNamespace(
        id=user_id, full_name=name, username=username, first_name=name, last_name=None
    )
    _LAST["message_id"] = msg.message_id
    return CommandContext(
        bot=bot, message=msg, connection=connection, args="", locale="ru"
    )


async def start_ttt(bot, connection):
    ctx = command_ctx(bot, connection, ANYA, "Аня", "anya")
    await cmd_ttt(ctx)
    return ctx


async def test_ttt_full_game_with_mentions(connection, bot):
    ctx = await start_ttt(bot, connection)
    # приглашение: упоминание стартера, parse_mode=html, в БД только id
    sent = bot.edited[-1]
    assert (
        sent["parse_mode"] == "html"
        and '<a href="https://t.me/anya">Аня</a>' in sent["text"]
    )
    game = await db.get_ttt_game(CONNECTION_ID, CHAT)
    assert (
        game["player_x_id"] == ANYA
        and "player_x_name" not in game
        and "player_o_name" not in game
    )

    accept = Call("ttt:accept", BORIS, "Боря")
    await on_ttt_callback(accept, bot)
    text = accept.edits[-1]["text"]
    assert accept.edits[-1]["parse_mode"] == "html"
    assert (
        "Аня" in text and '<a href="tg://user?id=8">Боря</a>' in text
    )  # имя Бори — из апдейта

    # X: 0,1,2 — победа по верхней линии; O: 3,4
    for user, name, cell in [
        (ANYA, "Аня", 0),
        (BORIS, "Боря", 3),
        (ANYA, "Аня", 1),
        (BORIS, "Боря", 4),
        (ANYA, "Аня", 2),
    ]:
        move = Call(f"ttt:{cell}", user, name)
        await on_ttt_callback(move, bot)
    assert "Победа" in move.edits[-1]["text"] and "Аня" in move.edits[-1]["text"]
    assert (await db.get_ttt_game(CONNECTION_ID, CHAT))["status"] == "finished"


async def test_ttt_rules_are_enforced(connection, bot):
    await start_ttt(bot, connection)
    own = Call("ttt:accept", ANYA, "Аня")
    await on_ttt_callback(own, bot)
    assert (
        own.answers
        and (await db.get_ttt_game(CONNECTION_ID, CHAT))["status"] == "pending"
    )

    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    stranger = Call("ttt:0", 99, "Чужой")
    await on_ttt_callback(stranger, bot)
    assert stranger.edits == []  # чужой не ходит
    wrong_turn = Call("ttt:0", BORIS, "Боря")
    await on_ttt_callback(wrong_turn, bot)
    assert wrong_turn.edits == []  # сейчас ход X


async def test_ttt_other_player_name_is_resolved_via_api_after_restart(connection, bot):
    """Кеш пуст (перезапуск бота): имя второго игрока берётся из Bot API."""
    await start_ttt(bot, connection)
    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    mentions.clear_cache()
    bot.chat_names = {ANYA: ("Аня К", "anya"), BORIS: ("Борис", None)}
    move = Call("ttt:0", ANYA, "Аня К", "anya")
    await on_ttt_callback(move, bot)
    text = move.edits[-1]["text"]
    assert "Борис" in text and "Аня К" in text


async def test_ttt_unknown_player_gets_fallback_not_crash(connection, bot):
    await start_ttt(bot, connection)
    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    mentions.clear_cache()
    bot.chat_names = {}  # Telegram никого не знает
    move = Call("ttt:0", ANYA, "Аня")
    await on_ttt_callback(move, bot)
    assert "Игрок" in move.edits[-1]["text"]


async def test_ttt_restart_uses_same_placeholder_in_every_locale(connection, bot):
    await start_ttt(bot, connection)
    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    for cell, (user, name) in zip(
        (0, 3, 1, 4, 2), [(ANYA, "Аня"), (BORIS, "Боря")] * 3
    ):
        await on_ttt_callback(Call(f"ttt:{cell}", user, name), bot)
    restart = Call("ttt:restart", BORIS, "Боря")
    await on_ttt_callback(restart, bot)
    assert (
        "{mention}" not in restart.edits[-1]["text"]
        and "Боря" in restart.edits[-1]["text"]
    )
    assert (await db.get_ttt_game(CONNECTION_ID, CHAT))["player_x_id"] == BORIS


@pytest.mark.parametrize("locale", ["ru", "en", "uk"])
async def test_ttt_texts_render_in_every_locale(connection, bot, locale):
    from modules.ttt import _build_text, _players

    await start_ttt(bot, connection)
    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    game = await db.get_ttt_game(CONNECTION_ID, CHAT)
    players = await _players(bot, game, locale)
    for winner in (None, "X", "O", "draw"):
        text = _build_text(locale, game, winner, players)
        assert "{" not in text and "}" not in text


async def test_checkers_accept_and_text_use_mentions(connection, bot):
    ctx = command_ctx(bot, connection, ANYA, "Аня", "anya")
    await cmd_chk(ctx)
    assert (
        bot.edited[-1]["parse_mode"] == "html"
        and 'href="https://t.me/anya"' in bot.edited[-1]["text"]
    )
    game = await db.get_chk_game(CONNECTION_ID, CHAT)
    assert game["player_w_id"] == ANYA and "player_w_name" not in game

    accept = Call("chk:accept", BORIS, "Боря")
    await on_chk_callback(accept, bot)
    assert accept.edits[-1]["parse_mode"] == "html"
    assert "Аня" in accept.edits[-1]["text"] and "Боря" in accept.edits[-1]["text"]


async def test_minesweeper_start_without_name_column(connection, bot):
    from modules.minesweeper import cmd_ms

    await cmd_ms(command_ctx(bot, connection, ANYA, "Аня"))
    game = await db.get_ms_game(CONNECTION_ID, CHAT)
    assert game["starter_id"] == ANYA and "starter_name" not in game


# --- регрессии: падения, из-за которых игра «не принималась» ---------------


def test_ttt_keyboard_buttons_always_have_text():
    """Без text aiogram кидает ValidationError (так сломался «Принять»)."""
    from modules.ttt import _build_keyboard

    for board, finished in (
        (".........", False),
        ("XOX.O.XO.", False),
        ("XXXOO....", True),
    ):
        kb = _build_keyboard(board, finished, {0, 1, 2} if finished else None)
        assert all(b.text for row in kb.inline_keyboard for b in row)


async def test_ttt_stray_actions_do_not_crash(connection, bot):
    """Повторный accept / мусорные данные в активной игре — тихий ответ, не исключение."""
    await start_ttt(bot, connection)
    await on_ttt_callback(Call("ttt:accept", BORIS, "Боря"), bot)
    for data in (
        "ttt:accept",
        "ttt:decline",
        "ttt:restart",
        "ttt:99",
        "ttt:abc",
        "ttt:noop",
    ):
        call = Call(data, BORIS, "Боря")
        await on_ttt_callback(call, bot)
        assert call.answers and not call.edits
    assert (await db.get_ttt_game(CONNECTION_ID, CHAT))["status"] == "active"


async def test_ttt_failed_message_edit_does_not_leave_game_active(connection, bot):
    await start_ttt(bot, connection)
    accept = Call("ttt:accept", BORIS, "Боря")

    async def boom(*a, **kw):
        raise RuntimeError("telegram error")

    accept.message.edit_text = boom
    with pytest.raises(RuntimeError):
        await on_ttt_callback(accept, bot)
    game = await db.get_ttt_game(CONNECTION_ID, CHAT)
    assert game["status"] == "pending" and game["player_o_id"] is None
    # и повторное нажатие работает
    retry = Call("ttt:accept", BORIS, "Боря")
    await on_ttt_callback(retry, bot)
    assert (await db.get_ttt_game(CONNECTION_ID, CHAT))["status"] == "active"


async def test_ttt_buttons_of_old_message_do_not_touch_new_game(connection, bot):
    await start_ttt(bot, connection)
    old = Call("ttt:accept", BORIS, "Боря", message_id=1)  # другое сообщение
    await on_ttt_callback(old, bot)
    assert not old.edits
    assert (await db.get_ttt_game(CONNECTION_ID, CHAT))["status"] == "pending"


async def test_ttt_decline_and_restart_after_finish(connection, bot):
    await start_ttt(bot, connection)
    decline = Call("ttt:decline", BORIS, "Боря")
    await on_ttt_callback(decline, bot)
    assert "отклонён" in decline.edits[-1]["text"]
    assert (await db.get_ttt_game(CONNECTION_ID, CHAT))["status"] == "finished"
