"""`.waiting` — кто ждёт ответа прямо сейчас (в личку владельцу).

Работает и в бизнес-чате, и в личке с ботом (/waiting). Необязательный
аргумент — порог: `.waiting 2h`, `.waiting 1d`; без него берётся 1 час."""

import time

from core import database as db
from core.context import CommandContext
from core.readall import parse_filters
from core.registry import command
from core.reminders import find_waiting, render_list


@command(name="waiting", aliases=["ждут"], module="reminders", scope="both")
async def cmd_waiting(ctx: CommandContext):
    min_seconds = 3600
    if ctx.args.strip():
        parsed = parse_filters(ctx.args)
        if parsed is None or parsed.last_seconds is None:
            await ctx.usage_error(ctx.t("rem.usage"))
            return
        min_seconds = parsed.last_seconds

    items = await find_waiting(
        ctx.connection, min_seconds, int(time.time()), skip_reminded=False
    )
    if not items:
        await ctx.usage_error(ctx.t("rem.none"))
        return
    # список — только владельцу в личку: собеседники не должны видеть, кто «ждёт»
    text = await render_list(
        ctx.bot,
        ctx.connection,
        items,
        ctx.locale or await db.get_locale(ctx.connection["owner_id"]),
    )
    await ctx.usage_error(text, parse_mode="html", disable_web_page_preview=True)
