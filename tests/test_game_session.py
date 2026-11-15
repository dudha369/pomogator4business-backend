"""GameSession: одна таблица на все мини-игры."""

import pytest

from app.features.games.models import GameSession
from app.features.games.service import GAME_DEFAULTS, get_game, save_game

pytestmark = pytest.mark.usefixtures("database")

CONN, CHAT = "c1", 7


async def test_get_missing_game_returns_none():
    assert await get_game("ttt", CONN, CHAT) is None


async def test_save_applies_defaults_and_get_is_flat():
    await save_game("ttt", CONN, CHAT, player_x_id=5)
    game = await get_game("ttt", CONN, CHAT)
    assert game["board"] == "........."
    assert game["turn"] == "X"
    assert game["player_x_id"] == 5
    assert game["status"] == "active"
    assert game["message_id"] is None
    assert (game["connection_id"], game["chat_id"]) == (CONN, CHAT)


async def test_save_is_partial_merge():
    await save_game("ttt", CONN, CHAT, board="X........", message_id=42)
    await save_game("ttt", CONN, CHAT, turn="O", status="finished")
    game = await get_game("ttt", CONN, CHAT)
    assert (game["board"], game["turn"]) == ("X........", "O")
    assert (game["status"], game["message_id"]) == ("finished", 42)
    assert await GameSession.filter(game="ttt").count() == 1


async def test_games_and_chats_are_isolated():
    await save_game("ttt", CONN, CHAT, board="X........")
    await save_game("chk", CONN, CHAT, board="b")
    await save_game("ttt", CONN, CHAT + 1, board="O........")
    assert (await get_game("ttt", CONN, CHAT))["board"] == "X........"
    assert (await get_game("chk", CONN, CHAT))["board"] == "b"
    assert (await get_game("ttt", CONN, CHAT + 1))["board"] == "O........"


async def test_unknown_field_is_rejected():
    with pytest.raises(ValueError):
        await save_game("ttt", CONN, CHAT, bord="X........")
    assert await get_game("ttt", CONN, CHAT) is None


async def test_bool_fields_are_coerced_and_none_is_storable():
    await save_game("ms", CONN, CHAT, coop=1, flag_mode=0, starter_id=9)
    await save_game("ms", CONN, CHAT, starter_id=None)
    game = await get_game("ms", CONN, CHAT)
    assert game["coop"] is True and game["flag_mode"] is False
    assert game["starter_id"] is None
    assert game["phase"] == "settings"  # у сапёра нет status в дефолтах — не мешает


async def test_big_telegram_ids_survive_json():
    big = 7_000_000_000_123
    await save_game("chk", CONN, CHAT, player_w_id=big)
    assert (await get_game("chk", CONN, CHAT))["player_w_id"] == big


@pytest.mark.parametrize("game", sorted(GAME_DEFAULTS))
async def test_every_game_roundtrips_its_defaults(game):
    await save_game(game, CONN, CHAT)
    stored = await get_game(game, CONN, CHAT)
    for key, value in GAME_DEFAULTS[game].items():
        assert stored[key] == value
