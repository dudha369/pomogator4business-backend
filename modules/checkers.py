from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.i18n import t
from core.registry import command

router = Router(name="chk")

_SIZE = 8
_DIAGONALS = [(-1, -1), (-1, 1), (1, -1), (1, 1)]

_SYMBOLS = {
    ".": "⠀",
    " ": "⠀",
    "w": "⚪",
    "W": "🤍",
    "b": "⚫",
    "B": "🖤",
}


def is_dark(row, col):
    return (row + col) % 2 == 1


def initial_board():
    cells = []
    for row in range(_SIZE):
        for col in range(_SIZE):
            if not is_dark(row, col):
                cells.append(" ")
            elif row <= 2:
                cells.append("b")
            elif row >= 5:
                cells.append("w")
            else:
                cells.append(".")
    return "".join(cells)


def _owner(cell):
    if cell in ("w", "W"):
        return "w"
    if cell in ("b", "B"):
        return "b"
    return None


def _is_king(cell):
    return cell in ("W", "B")


def _man_forward_dirs(color):
    # Белые идут к строке 0, чёрные — к строке 7 (см. initial_board).
    return [(-1, -1), (-1, 1)] if color == "w" else [(1, -1), (1, 1)]


def man_quiet_moves(board, idx):
    row, col = divmod(idx, _SIZE)
    color = _owner(board[idx])
    moves = []
    for dr, dc in _man_forward_dirs(color):
        nr, nc = row + dr, col + dc
        if 0 <= nr < _SIZE and 0 <= nc < _SIZE and board[nr * _SIZE + nc] == ".":
            moves.append(nr * _SIZE + nc)
    return moves


def man_captures(board, idx):
    """Простая шашка бьёт в любом из 4 диагональных направлений (и назад
    тоже — это правило русских шашек, не упрощённого варианта)."""
    row, col = divmod(idx, _SIZE)
    color = _owner(board[idx])
    results = []
    for dr, dc in _DIAGONALS:
        mr, mc = row + dr, col + dc
        lr, lc = row + 2 * dr, col + 2 * dc
        if not (0 <= lr < _SIZE and 0 <= lc < _SIZE):
            continue
        mid_idx = mr * _SIZE + mc
        land_idx = lr * _SIZE + lc
        mid_owner = _owner(board[mid_idx])
        if mid_owner is not None and mid_owner != color and board[land_idx] == ".":
            results.append((land_idx, mid_idx))
    return results


def king_quiet_moves(board, idx):
    """Дамка ходит на любое число свободных клеток по диагонали ("летающая" дамка)."""
    row, col = divmod(idx, _SIZE)
    moves = []
    for dr, dc in _DIAGONALS:
        r, c = row + dr, col + dc
        while 0 <= r < _SIZE and 0 <= c < _SIZE and board[r * _SIZE + c] == ".":
            moves.append(r * _SIZE + c)
            r += dr
            c += dc
    return moves


def king_captures(board, idx):
    row, col = divmod(idx, _SIZE)
    color = _owner(board[idx])
    results = []
    for dr, dc in _DIAGONALS:
        r, c = row + dr, col + dc
        while 0 <= r < _SIZE and 0 <= c < _SIZE and board[r * _SIZE + c] == ".":
            r += dr
            c += dc
        if not (0 <= r < _SIZE and 0 <= c < _SIZE):
            continue
        mid_idx = r * _SIZE + c
        mid_owner = _owner(board[mid_idx])
        if mid_owner is None or mid_owner == color:
            continue
        lr, lc = r + dr, c + dc
        while 0 <= lr < _SIZE and 0 <= lc < _SIZE and board[lr * _SIZE + lc] == ".":
            results.append((lr * _SIZE + lc, mid_idx))
            lr += dr
            lc += dc
    return results


def piece_captures(board, idx):
    return (
        king_captures(board, idx) if _is_king(board[idx]) else man_captures(board, idx)
    )


def piece_quiet_moves(board, idx):
    return (
        king_quiet_moves(board, idx)
        if _is_king(board[idx])
        else man_quiet_moves(board, idx)
    )


def color_has_any_capture(board, color):
    return any(
        _owner(cell) == color and piece_captures(board, idx)
        for idx, cell in enumerate(board)
    )


def legal_actions_for(board, idx, color):
    """{клетка_назначения: индекс_сбитой_шашки_или_None} для данной шашки,
    с учётом обязательного взятия: если ЛЮБАЯ своя шашка на доске может
    бить, тихие ходы недоступны вообще никому, включая эту шашку."""
    if _owner(board[idx]) != color:
        return {}

    captures = dict(piece_captures(board, idx))
    if color_has_any_capture(board, color):
        return captures  # пусто, если конкретно эта шашка бить не может

    return {land: None for land in piece_quiet_moves(board, idx)}


def apply_single_move(board, from_idx, to_idx, captured_idx):
    cells = list(board)
    piece = cells[from_idx]
    cells[from_idx] = "."
    if captured_idx is not None:
        cells[captured_idx] = "."
    cells[to_idx] = piece
    return "".join(cells)


def maybe_promote(board, idx):
    """Превращение в дамку — ТОЛЬКО когда боевая серия (или тихий ход)
    закончилась именно на последней горизонтали. Если шашка прошла через
    неё транзитом в середине серии боёв, она дамкой не становится."""
    cells = list(board)
    piece = cells[idx]
    row = idx // _SIZE
    if piece == "w" and row == 0:
        cells[idx] = "W"
    elif piece == "b" and row == _SIZE - 1:
        cells[idx] = "B"
    return "".join(cells)


def count_pieces(board, color):
    return sum(1 for cell in board if _owner(cell) == color)


def has_any_move(board, color):
    return any(
        _owner(cell) == color
        and (piece_captures(board, idx) or piece_quiet_moves(board, idx))
        for idx, cell in enumerate(board)
    )


def _challenge_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅", callback_data="chk:accept", style="success"
                ),
                InlineKeyboardButton(
                    text="❌", callback_data="chk:decline", style="danger"
                ),
            ]
        ]
    )


def _build_keyboard(board, selected, legal_landings=None):
    legal_landings = legal_landings or {}
    rows = []
    for r in range(_SIZE):
        row_buttons = []
        for c in range(_SIZE):
            idx = r * _SIZE + c
            cell = board[idx]

            if cell == " ":
                row_buttons.append(
                    InlineKeyboardButton(text=" ", callback_data="chk:noop")
                )
                continue

            if idx in legal_landings:
                text, style = "•", "success"
            else:
                text, style = _SYMBOLS[cell], None
                if selected == idx:
                    text += "🔲"

            kwargs = {"text": text, "callback_data": f"chk:{idx}"}
            if style:
                kwargs["style"] = style
            row_buttons.append(InlineKeyboardButton(**kwargs))
        rows.append(row_buttons)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _build_text(locale, game, winner, forced_continue=False):
    w_name = game["player_w_name"] or "?"
    b_name = game["player_b_name"] or "?"
    header = t("chk.header", locale, w_name=w_name, b_name=b_name)

    if winner:
        color_name = t("chk.white", locale) if winner == "w" else t("chk.black", locale)
        status = t("chk.win", locale, color=color_name)
    else:
        current = (
            t("chk.white", locale) if game["turn"] == "w" else t("chk.black", locale)
        )
        status = t("chk.turn", locale, color=current)
        if forced_continue:
            status += "\n" + t("chk.must_continue", locale)

    return header + "\n\n" + status


@command(name="chk", module="chk", owner_only=False)
async def cmd_chk(ctx):
    starter_name = ctx.message.from_user.full_name if ctx.message.from_user else "White"

    await db.save_chk_game(
        ctx.connection_id,
        ctx.chat_id,
        board=initial_board(),
        turn="w",
        player_w_id=ctx.message.from_user.id,
        player_w_name=starter_name,
        player_b_id=None,
        player_b_name=None,
        selected=None,
        forced_continue=False,
        status="pending",
        message_id=None,
    )

    text = t("chk.challenge", ctx.locale, name=starter_name)
    await ctx.edit_command_message(text, reply_markup=_challenge_keyboard())
    await db.save_chk_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


@router.callback_query(F.data.startswith("chk:"))
async def on_chk_callback(call: CallbackQuery):
    action = call.data.split(":", 1)[1]
    if action == "noop":
        await call.answer()
        return

    business_connection_id = call.message.business_connection_id
    chat_id = call.message.chat.id

    game = await db.get_chk_game(business_connection_id, chat_id)
    if not game:
        await call.answer()
        return

    connection = await db.get_connection(business_connection_id)
    locale = await db.get_locale(connection["owner_id"]) if connection else "ru"

    if game["status"] == "pending":
        if action == "decline":
            await db.save_chk_game(business_connection_id, chat_id, status="finished")
            await call.message.edit_text(t("chk.declined", locale))
            await call.answer()
            return
        if action == "accept":
            if call.from_user.id == game["player_w_id"]:
                await call.answer(t("chk.cant_accept_own", locale), show_alert=True)
                return
            await db.save_chk_game(
                business_connection_id,
                chat_id,
                player_b_id=call.from_user.id,
                player_b_name=call.from_user.full_name,
                status="active",
            )
            game = await db.get_chk_game(business_connection_id, chat_id)
            await call.message.edit_text(
                _build_text(locale, game, None),
                reply_markup=_build_keyboard(game["board"], None),
            )
            await call.answer()
            return
        await call.answer()
        return

    if game["status"] != "active":
        await call.answer()
        return

    user_id = call.from_user.id
    if user_id == game["player_w_id"]:
        color = "w"
    elif user_id == game["player_b_id"]:
        color = "b"
    else:
        await call.answer(t("chk.not_your_game", locale), show_alert=True)
        return

    if color != game["turn"]:
        await call.answer(t("chk.not_your_turn", locale), show_alert=True)
        return

    idx = int(action)
    board = game["board"]
    selected = game["selected"]
    forced_continue = game["forced_continue"]

    # Шашка в процессе серии боёв — можно только продолжать бить именно ею.
    if forced_continue:
        actions = dict(piece_captures(board, selected))
        if idx not in actions:
            await call.answer(t("chk.must_continue", locale), show_alert=True)
            return
        await _apply_move(
            call,
            business_connection_id,
            chat_id,
            locale,
            board,
            color,
            selected,
            idx,
            actions[idx],
        )
        return

    if selected is None:
        if _owner(board[idx]) != color:
            await call.answer()
            return
        actions = legal_actions_for(board, idx, color)
        if not actions:
            must_capture = color_has_any_capture(board, color)
            msg = "chk.must_capture_elsewhere" if must_capture else "chk.no_moves"
            await call.answer(t(msg, locale), show_alert=True)
            return
        await db.save_chk_game(business_connection_id, chat_id, selected=idx)
        await call.message.edit_reply_markup(
            reply_markup=_build_keyboard(board, idx, actions)
        )
        await call.answer()
        return

    if idx == selected:
        await db.save_chk_game(business_connection_id, chat_id, selected=None)
        await call.message.edit_reply_markup(reply_markup=_build_keyboard(board, None))
        await call.answer()
        return

    if _owner(board[idx]) == color:
        actions = legal_actions_for(board, idx, color)
        if not actions:
            must_capture = color_has_any_capture(board, color)
            msg = "chk.must_capture_elsewhere" if must_capture else "chk.no_moves"
            await call.answer(t(msg, locale), show_alert=True)
            return
        await db.save_chk_game(business_connection_id, chat_id, selected=idx)
        await call.message.edit_reply_markup(
            reply_markup=_build_keyboard(board, idx, actions)
        )
        await call.answer()
        return

    actions = legal_actions_for(board, selected, color)
    if idx not in actions:
        await call.answer(t("chk.invalid_move", locale), show_alert=True)
        return

    await _apply_move(
        call,
        business_connection_id,
        chat_id,
        locale,
        board,
        color,
        selected,
        idx,
        actions[idx],
    )


async def _apply_move(
    call,
    business_connection_id,
    chat_id,
    locale,
    board,
    color,
    from_idx,
    to_idx,
    captured_idx,
):
    new_board = apply_single_move(board, from_idx, to_idx, captured_idx)

    if captured_idx is not None:
        further = piece_captures(new_board, to_idx)
        if further:
            # Серия продолжается той же шашкой — ход не передаётся,
            # в дамки шашка пока не превращается (maybe_promote не вызывается).
            await db.save_chk_game(
                business_connection_id,
                chat_id,
                board=new_board,
                selected=to_idx,
                forced_continue=True,
            )
            game = await db.get_chk_game(business_connection_id, chat_id)
            await call.message.edit_text(
                _build_text(locale, game, None, forced_continue=True),
                reply_markup=_build_keyboard(new_board, to_idx, dict(further)),
            )
            await call.answer()
            return
        new_board = maybe_promote(new_board, to_idx)
    else:
        new_board = maybe_promote(new_board, to_idx)

    opponent = "b" if color == "w" else "w"
    winner = None
    if count_pieces(new_board, opponent) == 0 or not has_any_move(new_board, opponent):
        winner = color

    status = "finished" if winner else "active"
    next_turn = opponent if not winner else color

    await db.save_chk_game(
        business_connection_id,
        chat_id,
        board=new_board,
        turn=next_turn,
        selected=None,
        forced_continue=False,
        status=status,
    )
    game = await db.get_chk_game(business_connection_id, chat_id)

    await call.message.edit_text(
        _build_text(locale, game, winner),
        reply_markup=_build_keyboard(new_board, None),
    )
    await call.answer()
