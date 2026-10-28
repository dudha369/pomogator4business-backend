"""Шаблоны быстрых ответов: `.t имя` заменяет команду текстом шаблона.

Подстановки: {name}/{first_name} — имя собеседника, {full_name} — имя и фамилия.
Шаблоны создаются в мини-приложении. `.t` без аргумента показывает список
(только владельцу в личку — собеседник его не увидит)."""

from core import database as db
from core.autoresponder import render
from core.context import CommandContext
from core.registry import command


@command(name="tpl", aliases=["t", "шаблон"], module="templates")
async def cmd_template(ctx: CommandContext):
    owner_id = ctx.connection["owner_id"]
    name = ctx.args.strip().lower()

    if not name:
        templates = await db.list_templates(owner_id)
        if not templates:
            await ctx.usage_error(ctx.t("tpl.empty"))
        else:
            await ctx.usage_error(
                ctx.t("tpl.list", names=", ".join(tpl["name"] for tpl in templates))
            )
        return

    text = await db.get_template(owner_id, name)
    if text is None:
        await ctx.usage_error(ctx.t("tpl.not_found", name=name))
        return

    # владелец пишет в чат с собеседником: message.chat — это собеседник
    await ctx.edit_command_message(render(text, ctx.message.chat))
