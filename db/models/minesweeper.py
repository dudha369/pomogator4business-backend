from tortoise import fields
from tortoise.models import Model

from db.models._game_state import get_game, save_game


class MsGame(Model):
    id = fields.IntField(pk=True)
    connection_id = fields.CharField(max_length=255)
    chat_id = fields.BigIntField()
    size = fields.IntField(default=6)
    bomb_mode = fields.CharField(max_length=16, default="auto")
    coop = fields.BooleanField(default=False)
    mines = fields.TextField(default="[]")
    revealed = fields.TextField(default="")
    flagged = fields.TextField(default="[]")
    flag_mode = fields.BooleanField(default=False)
    starter_id = fields.BigIntField(null=True)
    starter_name = fields.CharField(max_length=255, null=True)
    phase = fields.CharField(max_length=16, default="settings")
    message_id = fields.BigIntField(null=True)

    class Meta:
        table = "ms_games"
        unique_together = (("connection_id", "chat_id"),)


_DEFAULTS = {
    "size": 6,
    "bomb_mode": "auto",
    "coop": False,
    "mines": "[]",
    "revealed": "",
    "flagged": "[]",
    "flag_mode": False,
    "starter_id": None,
    "starter_name": None,
    "phase": "settings",
    "message_id": None,
}


async def save_ms_game(connection_id, chat_id, **fields):
    fields = dict(fields)
    if "coop" in fields:
        fields["coop"] = bool(fields["coop"])
    if "flag_mode" in fields:
        fields["flag_mode"] = bool(fields["flag_mode"])
    await save_game(MsGame, connection_id, chat_id, _DEFAULTS, fields)


async def get_ms_game(connection_id, chat_id):
    return await get_game(MsGame, connection_id, chat_id)
