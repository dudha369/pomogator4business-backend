import asyncio
from random import shuffle

from core.context import CommandContext
from core.registry import command

_PHRASES = [
    "ХАХАХАХАХА",
    "🤣🤣🤣",
    "ой не могу",
    "вот умора",
    "😂😂😂",
    "ХА-ХА-ХА-ХА-ХА",
    "хахахахаха",
    "лол",
    "это реально смешно",
    "это реально приносит мне удовольствие",
    "я гнию на дне озера уже 5 лет",
    "😹😹😹",
    "обхохотаться можно",
    "с ума сойти!",
    "что ж ты со мной делаешь",
]


@command(name="haha", module="haha")
async def cmd_haha(ctx: CommandContext):
    shuffle(_PHRASES)

    await ctx.edit_command_message(_PHRASES[0])
    for phrase in _PHRASES[1:5]:
        await asyncio.sleep(0.4)
        await ctx.reply(phrase)
