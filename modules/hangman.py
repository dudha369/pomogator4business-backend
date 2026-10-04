import json
import random

from core import database as db
from core.i18n import t
from core.registry import command
from modules.wordle_dictionary import WORDS

_MAX_MISTAKES = 6

_STAGES = [
    " +---+\n |   |\n     |\n     |\n     |\n=========",
    " +---+\n |   |\n O   |\n     |\n     |\n=========",
    " +---+\n |   |\n O   |\n |   |\n     |\n=========",
    " +---+\n |   |\n O   |\n/|   |\n     |\n=========",
    " +---+\n |   |\n O   |\n/|\\  |\n     |\n=========",
    " +---+\n |   |\n O   |\n/|\\  |\n/    |\n=========",
    " +---+\n |   |\n O   |\n/|\\  |\n/ \\  |\n=========",
]


def _render(locale, game):
    guessed = json.loads(game["guessed_letters"])
    secret = game["secret"]
    display = " ".join(ch if ch in guessed else "_" for ch in secret)
    stage = _STAGES[min(game["mistakes"], _MAX_MISTAKES)]

    lines = [t("hangman.title", locale), f"<code>{stage}</code>", "", display, ""]

    if guessed:
        lines.append(t("hangman.guessed", locale, letters=", ".join(sorted(guessed))))

    if game["status"] == "won":
        lines.append(t("hangman.won", locale))
    elif game["status"] == "lost":
        lines.append(t("hangman.lost", locale, secret=secret))
    else:
        lines.append(
            t("hangman.hint", locale, mistakes=game["mistakes"], max=_MAX_MISTAKES)
        )

    return "\n".join(lines)


async def _start(ctx, secret):
    await db.save_hangman_game(
        ctx.connection_id,
        ctx.chat_id,
        secret=secret,
        guessed_letters="[]",
        mistakes=0,
        status="active",
        message_id=None,
    )
    game = await db.get_hangman_game(ctx.connection_id, ctx.chat_id)
    text = _render(ctx.locale, game)

    await ctx.edit_command_message(text)
    await db.save_hangman_game(
        ctx.connection_id, ctx.chat_id, message_id=ctx.message.message_id
    )


async def _handle_guess(ctx, game, letter):
    guessed = json.loads(game["guessed_letters"])
    if letter in guessed:
        await ctx.reply(ctx.t("hangman.already_guessed"))
        return

    guessed.append(letter)
    mistakes = game["mistakes"]
    if letter not in game["secret"]:
        mistakes += 1

    status = "active"
    if all(ch in guessed for ch in game["secret"]):
        status = "won"
    elif mistakes >= _MAX_MISTAKES:
        status = "lost"

    await db.save_hangman_game(
        ctx.connection_id,
        ctx.chat_id,
        guessed_letters=json.dumps(guessed, ensure_ascii=False),
        mistakes=mistakes,
        status=status,
    )
    game = await db.get_hangman_game(ctx.connection_id, ctx.chat_id)
    text = _render(ctx.locale, game)

    await ctx.delete_command_message()

    if game["message_id"]:
        try:
            await ctx.bot.edit_message_text(
                business_connection_id=ctx.connection_id,
                chat_id=ctx.chat_id,
                message_id=game["message_id"],
                text=text,
            )
            return
        except Exception:
            pass

    sent = await ctx.reply(text)
    await db.save_hangman_game(
        ctx.connection_id, ctx.chat_id, message_id=sent.message_id
    )


@command(name="hangman", module="hangman", owner_only=False)
async def cmd_hangman(ctx):
    raw = ctx.args.strip()
    game = await db.get_hangman_game(ctx.connection_id, ctx.chat_id)

    if game and game["status"] == "active" and len(raw) == 1 and raw.isalpha():
        await _handle_guess(ctx, game, raw.upper())
        return

    if raw and len(raw) > 1:
        secret = "".join(ch for ch in raw.upper() if ch.isalpha())
        if len(secret) < 3:
            await ctx.reply(ctx.t("hangman.invalid_word"))
            return
    else:
        secret = random.choice(WORDS)

    await _start(ctx, secret)
