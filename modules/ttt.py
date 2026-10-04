from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.i18n import t
from core.registry import command

router = Router(name="ttt")

_LINES = [
    (0, 1, 2),
    (3, 4, 5),
    (6, 7, 8),
    (0, 3, 6),
    (1, 4, 7),
    (2, 5, 8),
    (0, 4, 8),
    (2, 4, 6),
]
_SYMBOLS = {"X": "❌", "O": "⭕", ".": "⠀"}


def _check_winner(board):
    for a, b, c in _LINES:
        if board[a] != "." and board[a] == board[b] == board[c]:
            return board[a], {a, b, c}

    if "." not in board:
        return "draw", set()

    return None, set()


def _challenge_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅", callback_data="ttt:accept", style="success"
                ),
                InlineKeyboardButton(
                    text="❌", callback_data="ttt:decline", style="danger"
                ),
            ]
        ]
    )


def _build_keyboard(board, finished, winning_line=None):
    rows = []
    winning_line = winning_line or set()

    for r in range(3):
        row = []

        for c in range(3):
            idx = r * 3 + c
            cell = board[idx]

            if finished:
                callback_data = "ttt:noop"
            else:
                callback_data = f"ttt:{idx}" if cell == "." else "ttt:taken"

            button_kwargs = {
                "text": _SYMBOLS[cell],
                "callback_data": callback_data,
            }

            if idx in winning_line:
                button_kwargs["style"] = "success"

            row.append(InlineKeyboardButton(**button_kwargs))

        rows.append(row)

    if finished:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔄",
                    callback_data="ttt:restart",
                    style="primary",
                )
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_text(locale, game, winner):
    x_name = game["player_x_name"] or "X"
    o_name = game["player_o_name"] or "?"

    if winner == "draw":
        status = t("ttt.draw", locale)
    elif winner == "X":
        status = t("ttt.win", locale, symbol="❌", name=x_name)
    elif winner == "O":
        status = t("ttt.win", locale, symbol="⭕", name=o_name)
    else:
        current = "❌" if game["turn"] == "X" else "⭕"
        status = t("ttt.turn", locale, symbol=current)

    return t("ttt.header", locale, x_name=x_name, o_name=o_name) + "\n\n" + status


@command(name="ttt", module="ttt", owner_only=False)
async def cmd_ttt(ctx):
    starter_name = ctx.message.from_user.full_name if ctx.message.from_user else "X"

    await db.save_ttt_game(
        ctx.connection_id,
        ctx.chat_id,
        board=".........",
        turn="X",
        player_x_id=ctx.message.from_user.id,
        player_x_name=starter_name,
        player_o_id=None,
        player_o_name=None,
        status="pending",
        message_id=None,
    )

    text = t("ttt.challenge", ctx.locale, name=starter_name)
    await ctx.edit_command_message(text, reply_markup=_challenge_keyboard())
    await db.save_ttt_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


@router.callback_query(F.data.startswith("ttt:"))
async def on_ttt_callback(call: CallbackQuery):
    action = call.data.split(":", 1)[1]
    business_connection_id = call.message.business_connection_id
    chat_id = call.message.chat.id

    game = await db.get_ttt_game(business_connection_id, chat_id)
    if not game:
        await call.answer()
        return

    connection = await db.get_connection(business_connection_id)
    locale = await db.get_locale(connection["owner_id"]) if connection else "ru"

    if action == "noop":
        await call.answer()
        return

    if game["status"] == "pending":
        if action == "decline":
            await db.save_ttt_game(business_connection_id, chat_id, status="finished")
            await call.message.edit_text(t("ttt.declined", locale))
            await call.answer()
            return

        if action == "accept":
            if call.from_user.id == game["player_x_id"]:
                await call.answer(t("ttt.cant_accept_own", locale), show_alert=True)
                return
            await db.save_ttt_game(
                business_connection_id,
                chat_id,
                player_o_id=call.from_user.id,
                player_o_name=call.from_user.full_name,
                status="active",
            )
            game = await db.get_ttt_game(business_connection_id, chat_id)
            await call.message.edit_text(
                _build_text(locale, game, None),
                reply_markup=_build_keyboard(game["board"], False),
            )
            await call.answer()
            return

        await call.answer()
        return

    if action == "taken":
        await call.answer(t("ttt.cell_taken", locale), show_alert=False)
        return

    if action == "restart":
        starter_name = call.from_user.full_name
        await db.save_ttt_game(
            business_connection_id,
            chat_id,
            board=".........",
            turn="X",
            player_x_id=call.from_user.id,
            player_x_name=starter_name,
            player_o_id=None,
            player_o_name=None,
            status="pending",
            message_id=call.message.message_id,
        )
        await call.message.edit_text(
            t("ttt.challenge", locale, name=starter_name),
            reply_markup=_challenge_keyboard(),
        )
        await call.answer()
        return

    if game["status"] != "active":
        await call.answer()
        return

    idx = int(action)
    user_id = call.from_user.id

    if user_id == game["player_x_id"]:
        symbol = "X"
    elif user_id == game["player_o_id"]:
        symbol = "O"
    else:
        await call.answer(t("ttt.not_your_game", locale), show_alert=True)
        return

    if symbol != game["turn"]:
        await call.answer(t("ttt.not_your_turn", locale), show_alert=True)
        return

    board = list(game["board"])
    if board[idx] != ".":
        await call.answer(t("ttt.cell_taken", locale))
        return

    board[idx] = symbol
    board_str = "".join(board)

    winner, winning_line = _check_winner(board_str)

    next_turn = "O" if symbol == "X" else "X"
    status = "finished" if winner else "active"

    await db.save_ttt_game(
        business_connection_id,
        chat_id,
        board=board_str,
        turn=next_turn,
        status=status,
    )
    game = await db.get_ttt_game(business_connection_id, chat_id)

    await call.message.edit_text(
        _build_text(locale, game, winner),
        reply_markup=_build_keyboard(
            board_str,
            bool(winner),
            winning_line,
        ),
    )
    await call.answer()
