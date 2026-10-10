"""Команды в личке с ботом: `/readall 6h nofav` и `.readall` (с префиксом из
настроек подключения). Работают только команды со scope "bot" или "both"
(см. core/registry.py); остальные — только в бизнес-чатах.

Роутер подключается последним в bot_instance.setup_routes(), поэтому
служебные /start, /language, /archive и т.п. из handlers/settings.py
обрабатываются раньше и сюда не попадают."""

import logging

from aiogram import Bot, F, Router
from aiogram.types import Message

from core import database as db
from core.context import CommandContext
from core.i18n import t
from core.registry import registry

logger = logging.getLogger("bot.dm_commands")
router = Router(name="bot_commands")


def split_command(text: str, prefix: str):
    """'/readall@mybot 6h' -> ('readall', '6h'); '.readall' -> ('readall', '').
    Возвращает None, если текст не похож на команду."""
    text = text.strip()
    is_slash = text.startswith("/")
    if is_slash:
        body = text[1:]
    elif prefix and text.startswith(prefix):
        body = text[len(prefix):]
    else:
        return None

    body = body.strip()
    if not body:
        return None
    parts = body.split(maxsplit=1)
    alias = parts[0].lower()
    if is_slash:
        alias = alias.split("@", 1)[0]  # /cmd@botname
    return alias, (parts[1] if len(parts) > 1 else "")


@router.message(F.chat.type == "private", F.text)
async def on_dm_command(message: Message, bot: Bot):
    user = message.from_user
    if user is None:
        return

    connection = await db.get_connection_by_owner(user.id)
    prefix = connection["prefix"] if connection else "."
    parsed = split_command(message.text, prefix)
    if parsed is None:
        return
    alias, args = parsed

    cmd = registry.find(alias)
    if cmd is None and connection:
        target = await db.get_command_alias(user.id, alias)
        if target:
            cmd = registry.find(target)
    if cmd is None:
        return  # не наша команда — молчим, как и раньше

    locale = await db.get_locale(user.id)

    if cmd.scope not in ("bot", "both"):
        # подсказываем только для явных /команд, чтобы не отвечать на любой «.текст»
        if message.text.startswith("/"):
            await message.answer(t("common.chat_only_command", locale))
        return

    if not connection or not connection["is_enabled"]:
        await message.answer(t("common.not_connected", locale))
        return

    if cmd.module in await db.list_disabled_modules(connection["connection_id"]):
        await message.answer(t("common.module_disabled", locale))
        return

    ctx = CommandContext(
        bot=bot,
        message=message,
        connection=connection,
        args=args,
        locale=locale,
        dm=True,
    )
    try:
        await cmd.handler(ctx)
    except Exception:
        logger.exception("Сбой команды %s в личке", cmd.name)
