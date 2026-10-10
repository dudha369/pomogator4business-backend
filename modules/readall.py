"""Пометка чатов прочитанными (.readall) и избранные чаты (.fav).

.readall работает и в бизнес-чате, и в личке с ботом (/readall, .readall);
.fav — только в бизнес-чате, так как помечает текущий чат. Те же действия
доступны в мини-приложении (страница «Чаты»)."""

from core import database as db
from core.context import CommandContext
from core.readall import parse_filters, read_chats
from core.registry import command


@command(name="readall", aliases=["прочитать"], module="readall", scope="both")
async def cmd_readall(ctx: CommandContext):
    flt = parse_filters(ctx.args)
    if flt is None:
        await ctx.usage_error(ctx.t("readall.usage"))
        return

    result = await read_chats(ctx.bot, ctx.connection, flt)
    if result["matched"] == 0:
        await ctx.edit_command_message(ctx.t("readall.nothing"))
    elif result["done"] == 0:
        await ctx.edit_command_message(ctx.t("readall.failed"))
    elif result["failed"]:
        await ctx.edit_command_message(
            ctx.t("readall.done_partial", done=result["done"], total=result["matched"])
        )
    else:
        await ctx.edit_command_message(ctx.t("readall.done", done=result["done"]))


@command(name="fav", aliases=["избранное"], module="readall")
async def cmd_fav(ctx: CommandContext):
    now_favorite = await db.toggle_favorite_chat(
        ctx.connection["owner_id"], ctx.chat_id
    )
    await ctx.edit_command_message(
        ctx.t("fav.added" if now_favorite else "fav.removed")
    )
