import json

from app.features.games.lock import serialized_command
from app.platform.telegram.registry import command
from app.features.games.service import get_game, save_game

_SKIP_LETTERS = "ЬЪЫЙ"


def next_letter(word):
    word = word.upper()
    if len(word) > 1 and word[-1] in _SKIP_LETTERS:
        return word[-2]
    return word[-1]


def is_valid_city_text(word):
    if len(word) < 2:
        return False
    return all(ch.isalpha() or ch in " -" for ch in word)


@command(name="city", module="city", owner_only=False)
@serialized_command
async def cmd_city(ctx):
    raw = ctx.args.strip()

    if raw.lower() == "stop":
        await save_game("city", ctx.connection_id, ctx.chat_id, status="finished")
        await ctx.reply(ctx.t("city.stopped"))
        return

    if not is_valid_city_text(raw):
        await ctx.usage_error(ctx.t("city.usage"))
        return

    city = raw.upper()
    game = await get_game("city", ctx.connection_id, ctx.chat_id)

    if not game or game["status"] != "active":
        await save_game(
            "city",
            ctx.connection_id,
            ctx.chat_id,
            used_words=json.dumps([city], ensure_ascii=False),
            next_letter=next_letter(city),
            status="active",
        )
        await ctx.reply(ctx.t("city.started", city=city, letter=next_letter(city)))
        return

    used = json.loads(game["used_words"])

    if city in used:
        await ctx.reply(ctx.t("city.already_used", city=city))
        return

    if city[0] != game["next_letter"]:
        await ctx.reply(ctx.t("city.wrong_letter", letter=game["next_letter"]))
        return

    used.append(city)
    new_next = next_letter(city)
    await save_game(
        "city",
        ctx.connection_id,
        ctx.chat_id,
        used_words=json.dumps(used, ensure_ascii=False),
        next_letter=new_next,
    )
    await ctx.reply(ctx.t("city.accepted", city=city, letter=new_next))
