import random

from core import database as db
from core.i18n import t
from core.registry import command

_DEFAULT_MAX = 100


@command(name="guess", module="guess", owner_only=False)
async def cmd_guess(ctx):
    raw = ctx.args.strip()
    game = await db.get_guess_game(ctx.connection_id, ctx.chat_id)

    if game and game["status"] == "active" and raw.lstrip("-").isdigit():
        number = int(raw)
        attempts = game["attempts"] + 1
        secret = game["secret"]

        if number == secret:
            await db.save_guess_game(
                ctx.connection_id, ctx.chat_id, status="finished", attempts=attempts
            )
            await ctx.answer(
                t("guess.correct", ctx.locale, secret=secret, attempts=attempts)
            )
            return

        await db.save_guess_game(ctx.connection_id, ctx.chat_id, attempts=attempts)
        hint = (
            t("guess.higher", ctx.locale)
            if number < secret
            else t("guess.lower", ctx.locale)
        )
        await ctx.answer(hint)
        return

    max_value = int(raw) if raw.isdigit() and int(raw) >= 2 else _DEFAULT_MAX
    secret = random.randint(1, max_value)

    await db.save_guess_game(
        ctx.connection_id,
        ctx.chat_id,
        secret=secret,
        max_value=max_value,
        attempts=0,
        status="active",
    )
    await ctx.answer(t("guess.started", ctx.locale, max=max_value))
