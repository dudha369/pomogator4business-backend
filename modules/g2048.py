import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.i18n import t
from core.registry import command

router = Router(name="g2048")

_SIZE = 4


def _get_rows(board):
    return [board[r * _SIZE : (r + 1) * _SIZE] for r in range(_SIZE)]


def _rows_to_board(rows):
    return [v for row in rows for v in row]


def transpose(board):
    rows = _get_rows(board)
    cols = [[rows[r][c] for r in range(_SIZE)] for c in range(_SIZE)]
    return _rows_to_board(cols)


def slide_row_left(row):
    non_zero = [v for v in row if v != 0]
    merged = []
    points = 0
    i = 0
    while i < len(non_zero):
        if i + 1 < len(non_zero) and non_zero[i] == non_zero[i + 1]:
            value = non_zero[i] * 2
            merged.append(value)
            points += value
            i += 2
        else:
            merged.append(non_zero[i])
            i += 1
    merged += [0] * (len(row) - len(merged))
    return merged, points


def move(board, direction):
    rows = (
        _get_rows(board)
        if direction in ("left", "right")
        else _get_rows(transpose(board))
    )
    new_rows = []
    total_points = 0
    changed = False

    for row in rows:
        if direction in ("right", "down"):
            working = row[::-1]
        else:
            working = row

        new_working, points = slide_row_left(working)

        if direction in ("right", "down"):
            new_row = new_working[::-1]
        else:
            new_row = new_working

        if new_row != row:
            changed = True
        total_points += points
        new_rows.append(new_row)

    new_board = _rows_to_board(new_rows)
    if direction in ("up", "down"):
        new_board = transpose(new_board)

    return new_board, total_points, changed


def spawn_tile(board, rng=None):
    rng = rng or random
    empty = [i for i, v in enumerate(board) if v == 0]
    if not empty:
        return board
    idx = rng.choice(empty)
    value = 4 if rng.random() < 0.1 else 2
    new_board = list(board)
    new_board[idx] = value
    return new_board


def has_moves(board):
    if 0 in board:
        return True
    for row in _get_rows(board):
        for i in range(_SIZE - 1):
            if row[i] == row[i + 1]:
                return True
    for col in _get_rows(transpose(board)):
        for i in range(_SIZE - 1):
            if col[i] == col[i + 1]:
                return True
    return False


def has_won(board):
    return any(v >= 2048 for v in board)


def new_board(rng=None):
    board = [0] * (_SIZE * _SIZE)
    board = spawn_tile(board, rng)
    board = spawn_tile(board, rng)
    return board


def _board_to_str(board):
    return ",".join(str(v) for v in board)


def _board_from_str(raw):
    return [int(v) for v in raw.split(",")]


def _keyboard(board, finished):
    rows = []

    max_tile = max((v for v in board if v != 0), default=0)

    for r in range(_SIZE):
        row_buttons = []

        for c in range(_SIZE):
            v = board[r * _SIZE + c]
            text = str(v) if v else "⠀"

            callback_data = "g2048:noop"

            button_kwargs = {
                "text": text,
                "callback_data": callback_data,
            }

            if v != 0 and v == max_tile:
                button_kwargs["style"] = "success"

            row_buttons.append(InlineKeyboardButton(**button_kwargs))

        rows.append(row_buttons)

    rows.append(
        [
            InlineKeyboardButton(
                text="⬅️",
                callback_data="g2048:left" if not finished else "g2048:noop",
                style="primary" if not finished else None,
            ),
            InlineKeyboardButton(
                text="⬆️",
                callback_data="g2048:up" if not finished else "g2048:noop",
                style="primary" if not finished else None,
            ),
            InlineKeyboardButton(
                text="⬇️",
                callback_data="g2048:down" if not finished else "g2048:noop",
                style="primary" if not finished else None,
            ),
            InlineKeyboardButton(
                text="➡️",
                callback_data="g2048:right" if not finished else "g2048:noop",
                style="primary" if not finished else None,
            ),
            InlineKeyboardButton(
                text="🔄",
                callback_data="g2048:restart",
                style="danger" if not finished else "primary",
            ),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _text(locale, score, status):
    if status == "won":
        return t("g2048.won", locale, score=score)
    if status == "lost":
        return t("g2048.lost", locale, score=score)
    return t("g2048.score", locale, score=score)


@command(name="2048", module="g2048", owner_only=False)
async def cmd_2048(ctx):
    board = new_board()
    await db.save_g2048_game(
        ctx.connection_id,
        ctx.chat_id,
        board=_board_to_str(board),
        score=0,
        status="active",
        player_id=ctx.message.from_user.id,
        message_id=None,
    )

    text = _text(ctx.locale, 0, "active")
    keyboard = _keyboard(board, False)

    await ctx.edit_command_message(text, reply_markup=keyboard)
    await db.save_g2048_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


@router.callback_query(F.data.startswith("g2048:"))
async def on_2048_callback(call: CallbackQuery):
    action = call.data.split(":", 1)[1]
    if action == "noop":
        await call.answer()
        return

    business_connection_id = call.message.business_connection_id
    chat_id = call.message.chat.id

    game = await db.get_g2048_game(business_connection_id, chat_id)
    if not game:
        await call.answer()
        return

    connection = await db.get_connection(business_connection_id)
    locale = await db.get_locale(connection["owner_id"]) if connection else "ru"

    if call.from_user.id != game["player_id"]:
        await call.answer(t("g2048.not_your_game", locale), show_alert=True)
        return

    if action == "restart":
        board = new_board()
        await db.save_g2048_game(
            business_connection_id,
            chat_id,
            board=_board_to_str(board),
            score=0,
            status="active",
        )
        await call.message.edit_text(
            _text(locale, 0, "active"), reply_markup=_keyboard(board, False)
        )
        await call.answer()
        return

    if game["status"] != "active":
        await call.answer()
        return

    if action not in ("left", "right", "up", "down"):
        await call.answer()
        return

    board = _board_from_str(game["board"])
    new_b, points, changed = move(board, action)

    if not changed:
        await call.answer()
        return

    new_b = spawn_tile(new_b)
    score = game["score"] + points

    status = "active"
    if has_won(new_b):
        status = "won"
    elif not has_moves(new_b):
        status = "lost"

    await db.save_g2048_game(
        business_connection_id,
        chat_id,
        board=_board_to_str(new_b),
        score=score,
        status=status,
    )

    await call.message.edit_text(
        _text(locale, score, status),
        reply_markup=_keyboard(new_b, status != "active"),
    )
    await call.answer()
