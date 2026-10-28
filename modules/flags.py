"""Режим «не беспокоить» для конкретного чата: .noauto, .noai и .noremind."""

from core import database as db
from core.context import CommandContext
from core.registry import command


async def _toggle(ctx: CommandContext, flag: str, on_key: str, off_key: str):
    current = await db.get_chat_flags(ctx.connection["owner_id"], ctx.chat_id)
    updated = await db.set_chat_flags(
        ctx.connection["owner_id"], ctx.chat_id, **{flag: not current[flag]}
    )
    # подтверждение — только владельцу в личку, чтобы собеседник не видел
    # служебных сообщений о том, что с ним «не беспокоятся»
    await ctx.usage_error(ctx.t(on_key if updated[flag] else off_key))


@command(name="noauto", module="autoreply")
async def cmd_noauto(ctx: CommandContext):
    await _toggle(ctx, "no_autoreply", "flags.noauto_on", "flags.noauto_off")


@command(name="noremind", module="reminders")
async def cmd_noremind(ctx: CommandContext):
    await _toggle(ctx, "no_remind", "flags.noremind_on", "flags.noremind_off")


@command(name="noai", module="autoreply")
async def cmd_noai(ctx: CommandContext):
    await _toggle(ctx, "no_ai", "flags.noai_on", "flags.noai_off")
