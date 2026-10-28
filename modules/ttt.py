from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.i18n import t
from core.mentions import format_mention, mention, remember
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
_SYMBOLS = {
    "X": '<tg-emoji emoji-id="5404337815045583229">❌</tg-emoji>',
    "O": '<tg-emoji emoji-id="5402467554356668905">⭕️</tg-emoji>',
    ".": "⠀",
}


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
                    text="<tg-emoji emoji-id='5258108352008823107'>✅</tg-emoji>",
                    callback_data="ttt:accept",
                    style="success",
                ),
                InlineKeyboardButton(
                    text="<tg-emoji emoji-id='5260342697075416641'>❌</tg-emoji>",
                    callback_data="ttt:decline",
                    style="danger",
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


async def _players(bot, game, locale):
    fallback = t("ttt.player", locale)
    return {
        "X": (
            await mention(bot, game["player_x_id"], fallback)
            if game["player_x_id"]
            else "X"
        ),
        "O": (
            await mention(bot, game["player_o_id"], fallback)
            if game["player_o_id"]
            else "O"
        ),
    }


def _build_text(locale, game, winner, players):
    if winner == "draw":
        status = t("ttt.draw", locale)
    elif winner in ("X", "O"):
        status = t("ttt.win", locale, symbol=_SYMBOLS[winner], name=players[winner])
    else:
        status = t("ttt.turn", locale, symbol=_SYMBOLS[game["turn"]])

    header = t("ttt.header", locale, x_name=players["X"], o_name=players["O"])
    return header + "\n\n" + status


@command(name="ttt", module="ttt", owner_only=False)
async def cmd_ttt(ctx):
    starter = ctx.message.from_user
    remember(starter)

    await db.save_ttt_game(
        ctx.connection_id,
        ctx.chat_id,
        board=".........",
        turn="X",
        player_x_id=starter.id,
        player_o_id=None,
        status="pending",
        message_id=None,
    )

    text = t(
        "ttt.challenge",
        ctx.locale,
        mention=format_mention(starter.full_name, starter.username, starter.id),
    )
    await ctx.edit_command_message(
        text, reply_markup=_challenge_keyboard(), parse_mode="html"
    )
    await db.save_ttt_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


@router.callback_query(F.data.startswith("ttt:"))
async def on_ttt_callback(call: CallbackQuery, bot: Bot):
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
            remember(call.from_user)
            await db.save_ttt_game(
                business_connection_id,
                chat_id,
                player_o_id=call.from_user.id,
                status="active",
            )
            game = await db.get_ttt_game(business_connection_id, chat_id)
            await call.message.edit_text(
                _build_text(locale, game, None, await _players(bot, game, locale)),
                reply_markup=_build_keyboard(game["board"], False),
                parse_mode="html",
            )
            await call.answer()
            return

        await call.answer()
        return

    if action == "taken":
        await call.answer(t("ttt.cell_taken", locale), show_alert=False)
        return

    if action == "restart":
        starter = call.from_user
        remember(starter)
        await db.save_ttt_game(
            business_connection_id,
            chat_id,
            board=".........",
            turn="X",
            player_x_id=starter.id,
            player_o_id=None,
            status="pending",
            message_id=call.message.message_id,
        )
        await call.message.edit_text(
            t(
                "ttt.challenge",
                locale,
                mention=format_mention(starter.full_name, starter.username, starter.id),
            ),
            reply_markup=_challenge_keyboard(),
            parse_mode="html",
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

    remember(call.from_user)
    await call.message.edit_text(
        _build_text(locale, game, winner, await _players(bot, game, locale)),
        reply_markup=_build_keyboard(
            board_str,
            bool(winner),
            winning_line,
        ),
        parse_mode="html",
    )
    await call.answer()
