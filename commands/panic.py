from app.features.history.service import forget_message_log, recent_message_log
from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from app.platform.telegram.self_actions import delete_own_messages

_MAX_COUNT = 1000
_CHUNK_SIZE = 100


def _chunks(items, size):
    for i in range(0, len(items), size):
        yield items[i : i + size]


@command(
    name="panic",
    aliases=["del"],
    module="panic",
)
async def cmd_panic(ctx: CommandContext):
    parts = ctx.args.split()
    if not parts or not parts[0].isdigit():
        await ctx.bot.send_message(
            chat_id=ctx.connection["owner_chat_id"],
            text=ctx.t("panic.usage_dm"),
        )
        return

    count = min(int(parts[0]), _MAX_COUNT)
    if count <= 0:
        return

    rows = await recent_message_log(ctx.connection_id, ctx.chat_id, count)
    for chunk in _chunks(rows, _CHUNK_SIZE):
        deleted = await delete_own_messages(
            ctx.bot, ctx.connection_id, ctx.chat_id, [mid for _, mid in chunk]
        )
        # журнал стираем только для удалённого: неудавшийся чанк можно повторить
        if deleted:
            await forget_message_log([log_id for log_id, _ in chunk])
