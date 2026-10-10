from aiogram.types import BufferedInputFile

from core.context import CommandContext
from core.ffmpeg import apply_audio_filter
from core.registry import command
from core.self_actions import delete_own_messages
from core import database as db
from core.utils import log_suppressed

_FILTERS = {
    "helium": "asetrate=48000*1.6,aresample=48000,atempo=1/1.6",
    "robot": "asetrate=48000*0.9,aresample=48000,atempo=1/0.9,vibrato=f=8:d=0.5",
    "echo": "aecho=0.8:0.9:1000:0.3",
}


@command(name="voice", module="voice")
async def cmd_voice(ctx: CommandContext):
    effect = ctx.args.strip().lower()

    if effect in ("off", ""):
        await db.set_voice_effect(ctx.connection_id, ctx.chat_id, None)
        await ctx.edit_command_message(ctx.t("voice.disabled"))
        return

    if effect not in _FILTERS:
        await ctx.usage_error(ctx.t("voice.usage"))
        return

    await db.set_voice_effect(ctx.connection_id, ctx.chat_id, effect)
    await ctx.edit_command_message(ctx.t("voice.enabled", effect=effect))


async def handle_voice_message(bot, connection, message) -> bool:
    effect = await db.get_voice_effect(connection["connection_id"], message.chat.id)
    if not effect:
        return False

    filter_str = _FILTERS.get(effect)
    if not filter_str:
        return False

    file = await bot.get_file(message.voice.file_id)
    buffer = await bot.download_file(file.file_path)
    original_bytes = buffer.read()

    processed = await apply_audio_filter(original_bytes, filter_str)
    if processed is None:
        return False

    await delete_own_messages(
        bot, connection["connection_id"], message.chat.id, [message.message_id]
    )

    try:
        await bot.send_voice(
            business_connection_id=connection["connection_id"],
            chat_id=message.chat.id,
            voice=BufferedInputFile(processed, filename="voice.ogg"),
        )
    except Exception:
        log_suppressed("modules/voice_effects.py:60")

    return True
