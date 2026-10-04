import time

from core.context import CommandContext
from core.registry import command
from core.utils import parse_duration
from core.self_actions import delete_own_messages
from core import database as db


@command(name="mute", module="mute")
async def cmd_mute(ctx: CommandContext):
    args = ctx.args.strip()
    existing = await db.get_mute(ctx.connection_id, ctx.chat_id)

    if not args:
        if existing:
            await db.clear_mute(ctx.connection_id, ctx.chat_id)
            await ctx.edit_command_message(ctx.t("mute.disabled"))
        else:
            await db.set_timed_mute(ctx.connection_id, ctx.chat_id, until=None)
            await ctx.edit_command_message(ctx.t("mute.enabled_forever"))
        return

    seconds = parse_duration(args)
    if seconds is None or seconds <= 0:
        await ctx.usage_error(ctx.t("mute.usage"))
        return

    until = int(time.time()) + seconds
    await db.set_timed_mute(ctx.connection_id, ctx.chat_id, until=until)
    await ctx.edit_command_message(ctx.t("mute.enabled_for", time=args))


@command(name="wmute", module="mute")
async def cmd_wmute(ctx: CommandContext):
    args = ctx.args.split()

    if not args:
        await db.clear_mute(ctx.connection_id, ctx.chat_id)
        await ctx.edit_command_message(ctx.t("wmute.disabled"))
        return

    if not args[0].isdigit():
        await ctx.usage_error(ctx.t("wmute.usage"))
        return

    warn_limit = int(args[0])
    warn_duration = None
    if len(args) > 1:
        warn_duration = parse_duration(args[1])
        if warn_duration is None:
            await ctx.reply(ctx.t("wmute.invalid_time"))
            return

    await db.set_warn_mute(ctx.connection_id, ctx.chat_id, warn_limit, warn_duration)
    await ctx.edit_command_message(ctx.t("wmute.enabled_after", count=warn_limit))


async def handle_incoming(bot, connection, message) -> bool:
    connection_id = connection["connection_id"]
    chat_id = message.chat.id

    row = await db.get_mute(connection_id, chat_id)
    if not row:
        return False

    now = int(time.time())

    if row["active"]:
        if row["until"] and now >= row["until"]:
            await db.clear_mute(connection_id, chat_id)
            return False
        await delete_own_messages(bot, connection_id, chat_id, [message.message_id])
        return True

    if row["warn_limit"]:
        new_count = row["warn_count"] + 1
        if new_count >= row["warn_limit"]:
            until = now + row["warn_duration"] if row["warn_duration"] else None
            await db.activate_from_warn(connection_id, chat_id, until)
            await delete_own_messages(bot, connection_id, chat_id, [message.message_id])
            return True
        await db.bump_warn_count(connection_id, chat_id, new_count)
        return False

    return False
