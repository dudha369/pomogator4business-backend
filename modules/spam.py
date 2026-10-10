import asyncio

from aiogram.exceptions import TelegramForbiddenError

from core.context import CommandContext
from core.registry import command
from core.spam_control import clamp, is_spam_active, start_spam, stop_spam
from core.utils import log_suppressed

_LIMIT = 100
# Задержка чуть больше, чем в зеркале: сообщения тут уходят от РЕАЛЬНОГО
# аккаунта владельца через Business API, а не от одноразового бота —
# бережём именно этот аккаунт от анти-спам детекторов Telegram.
_DELAY = 0.35


@command(
    name="spam",
    module="spam",
)
async def cmd_spam(ctx: CommandContext):
    parts = ctx.args.split(maxsplit=1)
    if len(parts) < 2 or not parts[0].isdigit():
        await ctx.usage_error(ctx.t("spam.usage", limit=_LIMIT))
        return

    requested = int(parts[0])
    text = parts[1]
    if requested <= 0:
        return

    if is_spam_active(ctx.connection_id):
        await ctx.usage_error(ctx.t("spam.already_running"))
        return

    count = clamp(requested, _LIMIT)
    await ctx.delete_command_message()

    if count < requested:
        try:
            await ctx.bot.send_message(
                chat_id=ctx.connection["owner_chat_id"],
                text=ctx.t(
                    "spam.clamped", requested=requested, count=count, limit=_LIMIT
                ),
            )
        except Exception:
            log_suppressed("modules/spam.py:46")

    start_spam(ctx.connection_id)
    try:
        for _ in range(count):
            try:
                await ctx.bot.send_message(
                    business_connection_id=ctx.connection_id,
                    chat_id=ctx.chat_id,
                    text=text,
                )
            except TelegramForbiddenError:
                break
            await asyncio.sleep(_DELAY)
    finally:
        stop_spam(ctx.connection_id)
