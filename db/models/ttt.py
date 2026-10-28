from tortoise import fields
from tortoise.models import Model

from ._game_state import get_game, save_game


class TttGame(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    board = fields.CharField(max_length=16, default=".........")
    turn = fields.CharField(max_length=1, default="X")
    player_x_id = fields.BigIntField(null=True)
    player_o_id = fields.BigIntField(null=True)
    status = fields.CharField(max_length=16, default="active")
    message_id = fields.BigIntField(null=True)

    class Meta:
        table = "ttt_games"
        unique_together = (("connection_id", "chat_id"),)


_DEFAULTS = {
    "board": ".........",
    "turn": "X",
    "player_x_id": None,
    "player_o_id": None,
    "status": "active",
    "message_id": None,
}


async def save_ttt_game(connection_id, chat_id, **fields):
    await save_game(TttGame, connection_id, chat_id, _DEFAULTS, fields)


async def get_ttt_game(connection_id, chat_id):
    return await get_game(TttGame, connection_id, chat_id)
