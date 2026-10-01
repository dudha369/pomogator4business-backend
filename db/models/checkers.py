from tortoise import fields
from tortoise.models import Model

from db.models._game_state import get_game, save_game


class ChkGame(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    board = fields.TextField(default="")
    turn = fields.CharField(max_length=1, default="w")
    player_w_id = fields.BigIntField(null=True)
    player_w_name = fields.CharField(max_length=255, null=True)
    player_b_id = fields.BigIntField(null=True)
    player_b_name = fields.CharField(max_length=255, null=True)
    selected = fields.IntField(null=True)
    forced_continue = fields.BooleanField(default=False)
    status = fields.CharField(max_length=16, default="active")
    message_id = fields.BigIntField(null=True)

    class Meta:
        table = "chk_games"
        unique_together = (("connection_id", "chat_id"),)


_DEFAULTS = {
    "board": "",
    "turn": "w",
    "player_w_id": None,
    "player_w_name": None,
    "player_b_id": None,
    "player_b_name": None,
    "selected": None,
    "forced_continue": False,
    "status": "active",
    "message_id": None,
}


async def save_chk_game(connection_id, chat_id, **fields):
    fields = dict(fields)
    if "forced_continue" in fields:
        fields["forced_continue"] = bool(fields["forced_continue"])
    await save_game(ChkGame, connection_id, chat_id, _DEFAULTS, fields)


async def get_chk_game(connection_id, chat_id):
    return await get_game(ChkGame, connection_id, chat_id)
