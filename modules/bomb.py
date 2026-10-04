import asyncio

from core.context import CommandContext
from core.registry import command
from core.self_actions import delete_own_messages
from core.utils import parse_duration_loose

_MAX_SECONDS = 24 * 3600


async def _explode(bot, connection_id, chat_id, message_id, seconds):
    await asyncio.sleep(seconds)
    await delete_own_messages(bot, connection_id, chat_id, [message_id])


@command(
    name="bomb",
    aliases=["timerdel"],
    module="bomb",
)
async def cmd_bomb(ctx: CommandContext):
    target = ctx.message.reply_to_message

    if target:
        raw_time = ctx.args.strip().split()[0] if ctx.args.strip() else ""
        seconds = parse_duration_loose(raw_time)
        if seconds is None or seconds <= 0 or seconds > _MAX_SECONDS:
            await ctx.usage_error(ctx.t("bomb.usage_reply"))
            return

        await ctx.delete_command_message()
        asyncio.create_task(
            _explode(
                ctx.bot, ctx.connection_id, ctx.chat_id, target.message_id, seconds
            )
        )
        return

    parts = ctx.args.split(maxsplit=1)
    if len(parts) < 2:
        await ctx.usage_error(ctx.t("bomb.usage_full"))
        return

    raw_time, text = parts
    seconds = parse_duration_loose(raw_time)
    if seconds is None or seconds <= 0 or seconds > _MAX_SECONDS:
        await ctx.reply(ctx.t("bomb.invalid_time"))
        return

    await ctx.edit_command_message(text)

    asyncio.create_task(
        _explode(
            ctx.bot, ctx.connection_id, ctx.chat_id, ctx.message.message_id, seconds
        )
    )
