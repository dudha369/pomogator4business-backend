import random

from core.context import CommandContext
from core.registry import command
from modules.type_ import typewriter

_JOKES = [
    "Программист заходит в бар. Заказывает пиво. Заказывает 0 пива. Заказывает 999999999 пива. Заказывает ящерицу. Заказывает NULL пива. Бар взрывается.",
    "— Как дела? — Как в бинарном поиске: то лучше, то хуже, но в среднем логарифмически терпимо.",
    "Оптимист верит, что мы живём в лучшем из миров. Пессимист боится, что это правда.",
    "Штирлиц стрелял редко, но метко. Меткий и Редкий с тех пор так и не оправились.",
    "— Почему разработчики путают Хэллоуин и Рождество? — Потому что OCT 31 == DEC 25.",
    "Заходит улитка в бар, а её выгоняют. Через год она возвращается и говорит: 'И за что?'",
]


@command(
    name="joke",
    aliases=["анекдот"],
    module="joke",
)
async def cmd_joke(ctx: CommandContext):
    joke = random.choice(_JOKES)
    await typewriter(
        ctx.bot, ctx.connection, ctx.chat_id, joke, "▌", ctx.message.message_id
    )
