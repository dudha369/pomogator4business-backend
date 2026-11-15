import random

from app.features.games.lock import serialized_command
from app.platform.i18n import t
from app.platform.telegram.registry import command
from app.features.games.service import get_game, save_game

_DEFAULT_MAX = 100
# потолок в пределах INT Postgres (2**31 - 1), иначе save_game падает
_MAX_LIMIT = 1_000_000_000
# защита от int() на строках из тысяч цифр (лимит Python — 4300)
_MAX_DIGITS = 12


def _parse_int(raw: str) -> int | None:
    """Целое из аргумента команды или None. Только ASCII-цифры.

    Слишком длинное число не отвергаем, а зажимаем сверху: для активной игры это
    честное «меньше», а новая игра всё равно обрежется по _MAX_LIMIT."""
    body = raw.lstrip("-")
    if not (body.isascii() and body.isdigit()):
        return None
    value = int(body) if len(body) <= _MAX_DIGITS else _MAX_LIMIT * 10
    return -value if raw.startswith("-") else value


@command(name="guess", module="guess", owner_only=False)
@serialized_command
async def cmd_guess(ctx):
    raw = ctx.args.strip()
    game = await get_game("guess", ctx.connection_id, ctx.chat_id)

    number = _parse_int(raw)
    if game and game["status"] == "active" and number is not None:
        attempts = game["attempts"] + 1
        secret = game["secret"]

        if number == secret:
            await save_game(
                "guess",
                ctx.connection_id, ctx.chat_id, status="finished", attempts=attempts
            )
            await ctx.reply(
                t("guess.correct", ctx.locale, secret=secret, attempts=attempts)
            )
            return

        await save_game("guess", ctx.connection_id, ctx.chat_id, attempts=attempts)
        hint = (
            t("guess.higher", ctx.locale)
            if number < secret
            else t("guess.lower", ctx.locale)
        )
        await ctx.reply(hint)
        return

    max_value = (
        min(number, _MAX_LIMIT) if number is not None and number >= 2 else _DEFAULT_MAX
    )
    secret = random.randint(1, max_value)

    await save_game(
        "guess",
        ctx.connection_id,
        ctx.chat_id,
        secret=secret,
        max_value=max_value,
        attempts=0,
        status="active",
    )
    await ctx.reply(t("guess.started", ctx.locale, max=max_value))
