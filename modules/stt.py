from core.context import CommandContext
from core.registry import command
from core.stt import transcribe_audio

_MAX_DURATION_SECONDS = 120


def _extract_target(message):
    if message.voice:
        return message.voice.file_id, message.voice.duration
    if message.video_note:
        return message.video_note.file_id, message.video_note.duration
    return None, None


@command(name="stt", module="stt", description="Распознаёт речь из ГС или видео-кружка")
async def cmd_stt(ctx: CommandContext):
    target = ctx.message.reply_to_message
    file_id, duration = _extract_target(target) if target else (None, None)

    if not file_id:
        await ctx.usage_error(ctx.t("stt.usage"))
        return

    if duration and duration > _MAX_DURATION_SECONDS:
        await ctx.reply(ctx.t("stt.too_long", limit=_MAX_DURATION_SECONDS))
        return

    file = await ctx.bot.get_file(file_id)
    buffer = await ctx.bot.download_file(file.file_path)
    data = buffer.read()

    await ctx.reply(ctx.t("stt.processing"))
    text = await transcribe_audio(data, ctx.locale)

    if text is None:
        await ctx.reply(ctx.t("stt.failed"))
        return
    if not text:
        await ctx.reply(ctx.t("stt.empty"))
        return

    await ctx.reply(text)
