import asyncio

from deep_translator import GoogleTranslator

from core.context import CommandContext
from core.registry import command


@command(name="tr", module="tr")
async def cmd_tr(ctx: CommandContext):
    parts = ctx.args.split(maxsplit=1)
    if len(parts) < 2:
        await ctx.usage_error(ctx.t("tr.usage"))
        return

    lang, text = parts

    try:
        translated = await asyncio.to_thread(
            lambda: GoogleTranslator(source="auto", target=lang.lower()).translate(text)
        )
    except Exception:
        await ctx.edit_command_message(ctx.t("tr.failed"))
        return

    await ctx.edit_command_message(translated)
