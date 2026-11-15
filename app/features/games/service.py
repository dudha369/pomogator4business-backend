"""Состояние мини-игр: одна таблица `game_sessions` вместо таблицы на игру.

get_game(game, connection_id, chat_id) -> плоский dict (колонки + state) или None.
save_game(game, connection_id, chat_id, **fields) сохраняет ТОЛЬКО переданные
поля: значения по умолчанию ← существующая партия ← переданные поля.
"""

from tortoise.transactions import in_transaction

from .models import GameSession

# поля, которые живут в колонках, а не в JSON
_COLUMNS = ("status", "message_id")

GAME_DEFAULTS: dict[str, dict] = {
    "ttt": {
        "board": ".........",
        "turn": "X",
        "player_x_id": None,
        "player_o_id": None,
        "status": "active",
        "message_id": None,
    },
    "chk": {
        "board": "",
        "turn": "w",
        "player_w_id": None,
        "player_b_id": None,
        "selected": None,
        "forced_continue": False,
        "status": "active",
        "message_id": None,
    },
    "city": {"used_words": "[]", "next_letter": None, "status": "active"},
    "g2048": {
        "board": "",
        "score": 0,
        "player_id": None,
        "status": "active",
        "message_id": None,
    },
    "guess": {"secret": 1, "max_value": 100, "attempts": 0, "status": "active"},
    "hangman": {
        "secret": "",
        "guessed_letters": "[]",
        "mistakes": 0,
        "status": "active",
        "message_id": None,
    },
    "ms": {
        "size": 6,
        "bomb_mode": "auto",
        "coop": False,
        "mines": "[]",
        "revealed": "",
        "flagged": "[]",
        "flag_mode": False,
        "starter_id": None,
        "phase": "settings",
        "message_id": None,
    },
    "wordle": {
        "secret": "",
        "guesses": "[]",
        "starter_id": None,
        "status": "active",
        "message_id": None,
    },
}

# вызывающий код иногда передаёт 0/1 вместо bool
_BOOL_FIELDS = {"forced_continue", "coop", "flag_mode"}


def _flatten(row: GameSession, defaults: dict) -> dict:
    flat = {k: v for k, v in defaults.items() if k not in _COLUMNS}
    flat.update(row.state)
    flat.update(
        id=row.id,
        connection_id=row.connection_id,
        chat_id=row.chat_id,
        status=row.status,
        message_id=row.message_id,
    )
    return flat


async def get_game(game: str, connection_id, chat_id) -> dict | None:
    row = await GameSession.filter(
        connection_id=connection_id, chat_id=chat_id, game=game
    ).first()
    return _flatten(row, GAME_DEFAULTS[game]) if row else None


async def save_game(game: str, connection_id, chat_id, **fields) -> None:
    defaults = GAME_DEFAULTS[game]
    unknown = fields.keys() - defaults.keys()
    if unknown:  # опечатка в имени поля не должна молча уйти в JSON
        raise ValueError(f"{game}: неизвестные поля {sorted(unknown)}")
    for name in _BOOL_FIELDS & fields.keys():
        fields[name] = bool(fields[name])

    async with in_transaction():
        row = (
            await GameSession.filter(
                connection_id=connection_id, chat_id=chat_id, game=game
            )
            .select_for_update()
            .first()
        )
        merged = dict(defaults)
        if row:
            merged.update(_flatten(row, defaults))
        merged.update(fields)
        columns = {k: merged.pop(k) for k in _COLUMNS if k in merged}
        merged = {k: v for k, v in merged.items() if k in defaults}
        await GameSession.update_or_create(
            connection_id=connection_id,
            chat_id=chat_id,
            game=game,
            defaults={**columns, "state": merged},
        )
