import json
import random

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import database as db
from core.i18n import t
from core.registry import command

router = Router(name="ms")

_AUTO_BOMBS = {6: 6, 8: 9, 9: 12}
_NUMBER_EMOJI = {1: "1️⃣", 2: "2️⃣", 3: "3️⃣", 4: "4️⃣", 5: "5️⃣", 6: "6️⃣", 7: "7️⃣", 8: "8️⃣"}


def resolve_bomb_count(size, bomb_mode):
    if bomb_mode == "5":
        return 5
    if bomb_mode == "8":
        return 8
    return _AUTO_BOMBS.get(size, 6)


def generate_mines(size, bomb_count, rng=None):
    rng = rng or random
    total = size * size
    return set(rng.sample(range(total), min(bomb_count, total)))


def adjacent_count(size, mines, index):
    row, col = divmod(index, size)
    count = 0
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = row + dr, col + dc
            if 0 <= nr < size and 0 <= nc < size and (nr * size + nc) in mines:
                count += 1
    return count


def flood_reveal(size, mines, revealed, flagged, start_index):
    if start_index in revealed:
        return
    stack = [start_index]
    while stack:
        idx = stack.pop()
        if idx in revealed or idx in flagged:
            continue
        revealed.add(idx)
        if idx in mines:
            continue
        if adjacent_count(size, mines, idx) == 0:
            row, col = divmod(idx, size)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = row + dr, col + dc
                    if 0 <= nr < size and 0 <= nc < size:
                        nidx = nr * size + nc
                        if (
                            nidx not in revealed
                            and nidx not in mines
                            and nidx not in flagged
                        ):
                            stack.append(nidx)


def is_win(size, mines, revealed):
    return len(revealed - mines) == size * size - len(mines)


def _set_from_json(raw):
    return set(json.loads(raw)) if raw else set()


def _set_to_json(values):
    return json.dumps(list(values))


def _revealed_from_str(raw, size):
    return {i for i, ch in enumerate(raw) if ch == "1"}


def _revealed_to_str(revealed, size):
    return "".join("1" if i in revealed else "0" for i in range(size * size))


def _settings_keyboard(game):
    rows = []

    size_row = []
    for s in (6, 8, 9):
        mark = "✅ " if game["size"] == s else ""
        size_row.append(
            InlineKeyboardButton(text=f"{mark}{s}x{s}", callback_data=f"ms:size:{s}")
        )
    rows.append(size_row)

    bomb_row = []
    for mode, label in (("5", "5"), ("8", "8"), ("auto", "Auto")):
        mark = "✅ " if game["bomb_mode"] == mode else ""
        bomb_row.append(
            InlineKeyboardButton(
                text=f"{mark}{label}", callback_data=f"ms:bombs:{mode}"
            )
        )
    rows.append(bomb_row)

    coop_mark = "✅" if game["coop"] else "☑️"
    rows.append(
        [
            InlineKeyboardButton(
                text=f"{coop_mark} co-op", callback_data="ms:coop:toggle"
            )
        ]
    )
    rows.append(
        [InlineKeyboardButton(text="🎮", callback_data="ms:start", style="success")]
    )
    rows.append(
        [InlineKeyboardButton(text="🗑", callback_data="ms:stop", style="danger")]
    )

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _mode_button(locale, flag_mode):
    label = t("ms.mode_flag", locale) if flag_mode else t("ms.mode_open", locale)
    style = "danger" if flag_mode else "primary"
    return InlineKeyboardButton(text=label, callback_data="ms:mode", style=style)


def _game_keyboard(
    locale, size, mines, revealed, flagged, exploded_idx, finished, flag_mode
):
    rows = []
    for r in range(size):
        row_buttons = []
        for c in range(size):
            idx = r * size + c

            if idx in revealed or finished:
                if idx in mines:
                    text = "💥" if idx == exploded_idx else "💣"
                    style = "danger"
                elif idx in flagged:
                    # флаг стоял верно — подсветим как успех при завершении игры
                    text = "🚩"
                    style = "success" if finished and idx not in mines else None
                else:
                    count = adjacent_count(size, mines, idx)
                    text = _NUMBER_EMOJI.get(count, "·")
                    style = None
                callback_data = "ms:noop"
            elif idx in flagged:
                text = "🚩"
                style = "primary"
                callback_data = f"ms:cell:{idx}"
            else:
                text = "⬜"
                style = None
                callback_data = f"ms:cell:{idx}"

            kwargs = {"text": text, "callback_data": callback_data}
            if style:
                kwargs["style"] = style
            row_buttons.append(InlineKeyboardButton(**kwargs))
        rows.append(row_buttons)

    if not finished:
        rows.append(
            [
                _mode_button(locale, flag_mode),
                InlineKeyboardButton(text="🗑", callback_data="ms:stop", style="danger"),
            ]
        )

    return InlineKeyboardMarkup(inline_keyboard=rows)


@command(name="ms", module="ms", description="Сапёр", owner_only=False)
async def cmd_ms(ctx):
    starter_name = ctx.message.from_user.full_name if ctx.message.from_user else "?"

    await db.save_ms_game(
        ctx.connection_id,
        ctx.chat_id,
        size=6,
        bomb_mode="auto",
        coop=0,
        mines="[]",
        revealed="",
        flagged="[]",
        flag_mode=False,
        starter_id=ctx.message.from_user.id,
        starter_name=starter_name,
        phase="settings",
        message_id=None,
    )

    game = await db.get_ms_game(ctx.connection_id, ctx.chat_id)
    text = t("ms.settings_title", ctx.locale)
    keyboard = _settings_keyboard(game)

    await ctx.edit_command_message(text, reply_markup=keyboard)
    await db.save_ms_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


@router.callback_query(F.data.startswith("ms:"))
async def on_ms_callback(call: CallbackQuery):
    parts = call.data.split(":")
    action = parts[1]

    if action == "noop":
        await call.answer()
        return

    business_connection_id = call.message.business_connection_id
    chat_id = call.message.chat.id

    game = await db.get_ms_game(business_connection_id, chat_id)
    if not game:
        await call.answer()
        return

    connection = await db.get_connection(business_connection_id)
    locale = await db.get_locale(connection["owner_id"]) if connection else "ru"

    if action in ("size", "bombs", "coop", "start", "stop", "mode"):
        if call.from_user.id != game["starter_id"]:
            await call.answer(t("ms.not_starter", locale), show_alert=True)
            return

    if game["phase"] == "settings":
        if action == "size":
            await db.save_ms_game(business_connection_id, chat_id, size=int(parts[2]))
        elif action == "bombs":
            await db.save_ms_game(business_connection_id, chat_id, bomb_mode=parts[2])
        elif action == "coop":
            await db.save_ms_game(
                business_connection_id, chat_id, coop=0 if game["coop"] else 1
            )
        elif action == "stop":
            await call.message.edit_text(t("ms.cancelled", locale))
            await call.answer()
            return
        elif action == "start":
            size = game["size"]
            bomb_count = resolve_bomb_count(size, game["bomb_mode"])
            mines = generate_mines(size, bomb_count)
            await db.save_ms_game(
                business_connection_id,
                chat_id,
                mines=_set_to_json(mines),
                revealed=_revealed_to_str(set(), size),
                flagged=_set_to_json(set()),
                flag_mode=False,
                phase="active",
            )
            game = await db.get_ms_game(business_connection_id, chat_id)
            await call.message.edit_text(
                t("ms.playing", locale, size=size, bombs=bomb_count),
                reply_markup=_game_keyboard(
                    locale, size, mines, set(), set(), None, False, False
                ),
            )
            await call.answer()
            return
        else:
            await call.answer()
            return

        game = await db.get_ms_game(business_connection_id, chat_id)
        await call.message.edit_reply_markup(reply_markup=_settings_keyboard(game))
        await call.answer()
        return

    if game["phase"] != "active":
        await call.answer()
        return

    if action == "stop":
        await db.save_ms_game(business_connection_id, chat_id, phase="finished")
        await call.message.edit_text(t("ms.cancelled", locale))
        await call.answer()
        return

    size = game["size"]
    mines = _set_from_json(game["mines"])
    revealed = _revealed_from_str(game["revealed"], size)
    flagged = _set_from_json(game["flagged"])

    if action == "mode":
        new_mode = not game["flag_mode"]
        await db.save_ms_game(business_connection_id, chat_id, flag_mode=new_mode)
        await call.message.edit_reply_markup(
            reply_markup=_game_keyboard(
                locale, size, mines, revealed, flagged, None, False, new_mode
            )
        )
        await call.answer()
        return

    if action != "cell":
        await call.answer()
        return

    if not game["coop"] and call.from_user.id != game["starter_id"]:
        await call.answer(t("ms.not_starter", locale), show_alert=True)
        return

    idx = int(parts[2])
    if idx in revealed:
        await call.answer()
        return

    if game["flag_mode"]:
        flagged = set(flagged)
        if idx in flagged:
            flagged.discard(idx)
        else:
            flagged.add(idx)
        await db.save_ms_game(
            business_connection_id, chat_id, flagged=_set_to_json(flagged)
        )
        await call.message.edit_reply_markup(
            reply_markup=_game_keyboard(
                locale, size, mines, revealed, flagged, None, False, True
            )
        )
        await call.answer()
        return

    if idx in flagged:
        # сначала нужно снять флаг переключением режима — защищаем от случайного открытия
        await call.answer(t("ms.cell_flagged", locale), show_alert=True)
        return

    if idx in mines:
        revealed.add(idx)
        await db.save_ms_game(
            business_connection_id,
            chat_id,
            revealed=_revealed_to_str(revealed, size),
            phase="finished",
        )
        await call.message.edit_text(
            t("ms.lost", locale),
            reply_markup=_game_keyboard(
                locale, size, mines, revealed, flagged, idx, True, False
            ),
        )
        await call.answer()
        return

    flood_reveal(size, mines, revealed, flagged, idx)

    if is_win(size, mines, revealed):
        await db.save_ms_game(
            business_connection_id,
            chat_id,
            revealed=_revealed_to_str(revealed, size),
            phase="finished",
        )
        await call.message.edit_text(
            t("ms.won", locale),
            reply_markup=_game_keyboard(
                locale, size, mines, revealed, flagged, None, True, False
            ),
        )
        await call.answer()
        return

    await db.save_ms_game(
        business_connection_id, chat_id, revealed=_revealed_to_str(revealed, size)
    )
    await call.message.edit_reply_markup(
        reply_markup=_game_keyboard(
            locale, size, mines, revealed, flagged, None, False, game["flag_mode"]
        )
    )
    await call.answer()
