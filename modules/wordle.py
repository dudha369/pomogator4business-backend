import json
import random

from core import database as db
from core.i18n import t
from core.registry import command
from core.self_actions import delete_own_messages
from modules.wordle_dictionary import WORDS
from core.utils import log_suppressed

_MAX_ATTEMPTS = 6
_CIRCLES = {"green": "🟢", "blue": "🔵", "red": "🔴"}


def evaluate_guess(guess, secret):
    length = len(secret)
    result = ["red"] * length
    remaining = {}

    for i in range(length):
        if guess[i] == secret[i]:
            result[i] = "green"
        else:
            remaining[secret[i]] = remaining.get(secret[i], 0) + 1

    for i in range(length):
        if result[i] == "green":
            continue
        ch = guess[i]
        if remaining.get(ch, 0) > 0:
            result[i] = "blue"
            remaining[ch] -= 1

    return result


def _render_board(locale, secret_length, guesses, status, secret):
    lines = [
        t("wordle.title", locale),
        t("wordle.subtitle", locale, length=secret_length),
        t("wordle.legend_green", locale),
        t("wordle.legend_blue", locale),
        t("wordle.legend_red", locale),
        "",
    ]

    for guess in guesses:
        colors = evaluate_guess(guess, secret)
        lines.append(guess)
        lines.append("".join(_CIRCLES[c] for c in colors))

    remaining_rows = _MAX_ATTEMPTS - len(guesses)
    for _ in range(remaining_rows):
        lines.append("⬛" * secret_length)

    if status == "won":
        lines.append("")
        lines.append(t("wordle.won", locale))
    elif status == "lost":
        lines.append("")
        lines.append(t("wordle.lost", locale, secret=secret))
    else:
        lines.append("")
        lines.append(t("wordle.hint", locale))
        lines.append(t("wordle.attempts", locale, used=len(guesses), max=_MAX_ATTEMPTS))

    return "\n".join(lines)


@command(name="word", module="wordle", owner_only=False)
async def cmd_word(ctx):
    raw = ctx.args.strip().upper()
    if raw:
        secret = "".join(ch for ch in raw if ch.isalpha())
        if len(secret) < 3:
            await ctx.reply(t("wordle.invalid_word", ctx.locale))
            return
    else:
        secret = random.choice(WORDS)

    await db.save_wordle_game(
        ctx.connection_id,
        ctx.chat_id,
        secret=secret,
        guesses="[]",
        status="active",
        message_id=None,
        starter_id=ctx.message.from_user.id,
    )

    text = _render_board(ctx.locale, len(secret), [], "active", secret)
    await ctx.edit_command_message(text)
    await db.save_wordle_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


async def handle_wordle_guess(bot, connection, message, locale, raw_guess):
    game = await db.get_wordle_game(connection["connection_id"], message.chat.id)
    if not game or game["status"] != "active":
        return False

    secret = game["secret"]
    guess = "".join(ch for ch in raw_guess.upper() if ch.isalpha())
    if len(guess) != len(secret):
        return False

    guesses = json.loads(game["guesses"])
    guesses.append(guess)

    if guess == secret:
        status = "won"
    elif len(guesses) >= _MAX_ATTEMPTS:
        status = "lost"
    else:
        status = "active"

    await db.save_wordle_game(
        connection["connection_id"],
        message.chat.id,
        guesses=json.dumps(guesses, ensure_ascii=False),
        status=status,
    )

    text = _render_board(locale, len(secret), guesses, status, secret)

    await delete_own_messages(
        bot, connection["connection_id"], message.chat.id, [message.message_id]
    )

    try:
        if game["message_id"]:
            await bot.edit_message_text(
                business_connection_id=connection["connection_id"],
                chat_id=message.chat.id,
                message_id=game["message_id"],
                text=text,
            )
        else:
            sent = await bot.send_message(
                business_connection_id=connection["connection_id"],
                chat_id=message.chat.id,
                text=text,
            )
            await db.save_wordle_game(
                connection["connection_id"], message.chat.id, message_id=sent.message_id
            )
    except Exception:
        log_suppressed("modules/wordle.py:147", benign=True)

    return True
