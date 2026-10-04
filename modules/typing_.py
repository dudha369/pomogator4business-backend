import asyncio

from core.context import CommandContext
from core.registry import command
from core.utils import parse_duration

_MAX_SECONDS = 5 * 60
_STEP = 4

_ACTIONS = {
    "typing": "typing",
    "voice": "record_voice",
    "video": "upload_video",
    "file": "upload_document",
    "photo": "upload_photo",
    "round": "record_video_note",
    "sticker": "choose_sticker",
}


async def _keep_action(bot, connection_id, chat_id, action, seconds):
    elapsed = 0
    while elapsed < seconds:
        try:
            await bot.send_chat_action(
                business_connection_id=connection_id,
                chat_id=chat_id,
                action=action,
            )
        except Exception:
            return
        wait = min(_STEP, seconds - elapsed)
        await asyncio.sleep(wait)
        elapsed += wait


@command(name="typing", module="typing")
async def cmd_typing(ctx: CommandContext):
    parts = ctx.args.split()
    if not parts:
        await ctx.usage_error(ctx.t("typing.usage"))
        return

    seconds = parse_duration(parts[0])
    if seconds is None or seconds <= 0 or seconds > _MAX_SECONDS:
        await ctx.reply(ctx.t("typing.invalid_time"))
        return

    action_key = parts[1].lower() if len(parts) > 1 else "typing"
    action = _ACTIONS.get(action_key)
    if not action:
        await ctx.reply(ctx.t("typing.unknown_action"))
        return

    await ctx.delete_command_message()
    asyncio.create_task(
        _keep_action(ctx.bot, ctx.connection_id, ctx.chat_id, action, seconds)
    )
