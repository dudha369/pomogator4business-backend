"""Диспетчер команд: префикс → registry → CommandContext. Конечная точка цепочки
бизнес-сообщений (все middleware до него могли сообщение остановить)."""

import logging
import time

from app.platform.i18n import t
from app.platform.telegram.context import CommandContext
from app.platform.telegram.incoming import Incoming
from app.platform.telegram.registry import registry
from db.models.command_alias import get_command_alias
from db.models.user_locale import get_locale
from core.utils import log_suppressed

logger = logging.getLogger("bot.dispatch")

_FAILURE_NOTICE_INTERVAL = 60
_last_failure_notice: dict[tuple[str, str], float] = {}


async def dispatch_command(message, inc: Incoming):
    if not inc.text:
        return
    prefix = inc.connection["prefix"]
    if not inc.text.startswith(prefix):
        return

    body = inc.text[len(prefix) :].strip()
    if not body:
        return

    parts = body.split(maxsplit=1)
    alias = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    cmd = registry.find(alias)
    if not cmd:
        custom_target = await get_command_alias(inc.connection["owner_id"], alias)
        if custom_target:
            cmd = registry.find(custom_target)
    if not cmd:
        await _run_fallbacks(inc, alias)
        return

    if cmd.module in inc.disabled or (cmd.owner_only and not inc.is_owner):
        return

    ctx = CommandContext(
        bot=inc.bot,
        message=inc.message,
        connection=inc.connection,
        args=args,
        locale=await get_locale(inc.connection["owner_id"]),
    )
    try:
        await cmd.handler(ctx)
    except Exception:
        # команду часто удаляют ДО выполнения: без этого при сбое она исчезает молча
        logger.exception("Сбой команды %s", cmd.name)
        await report_command_failure(inc, cmd.name, ctx.locale)


async def _run_fallbacks(inc: Incoming, alias: str):
    for module, handler in registry.fallbacks():
        if inc.enabled(module):
            locale = await get_locale(inc.connection["owner_id"])
            await handler(inc.bot, inc.connection, inc.message, locale, alias)


async def report_command_failure(inc: Incoming, name: str, locale: str) -> None:
    """Сообщить владельцу, что команда не выполнилась (не чаще раза в минуту на команду)."""
    key, now = (inc.connection_id, name), time.monotonic()
    if (
        now - _last_failure_notice.get(key, -_FAILURE_NOTICE_INTERVAL)
        < _FAILURE_NOTICE_INTERVAL
    ):
        return
    _last_failure_notice[key] = now
    try:
        await inc.bot.send_message(
            chat_id=inc.connection["owner_chat_id"],
            text=t("cmd.failed", locale, name=name),
            parse_mode=None,
        )
    except Exception:
        log_suppressed("platform/telegram/dispatch.py:report_failure", benign=True)
