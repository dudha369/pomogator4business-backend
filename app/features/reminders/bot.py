"""`.waiting` — кто ждёт ответа прямо сейчас (в личку владельцу).

Работает и в бизнес-чате, и в личке с ботом (/waiting). Необязательный
аргумент — порог: `.waiting 2h`, `.waiting 1d`; без него берётся 1 час."""

import asyncio
import logging
import time

from app.features.reminders.service import (
    LOOP_INTERVAL_SECONDS,
    MAX_LINES,
    PREVIEW_LENGTH,
    find_waiting,
    format_waited,
    get_reminder_settings,
    is_quiet,
    list_reminder_owner_ids,
)
from app.platform.i18n import t
from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from app.platform.telegram.mentions import escape, mention
from app.features.chats.service import parse_filters
from app.features.autoresponder.queries import log_autoreply
from db.models.connection import get_connection_by_owner
from app.features.history.service import get_history_entry
from db.models.user_locale import get_locale, get_timezone_offset

logger = logging.getLogger("bot.reminders")


async def render_list(bot, connection, items, locale: str) -> str:
    """HTML-текст со списком ждущих чатов (имена — упоминаниями, текст экранирован)."""
    lines = [t("rem.header", locale)]
    for item in items[:MAX_LINES]:
        entry = await get_history_entry(
            connection["connection_id"], item["chat_id"], item["message_id"]
        )
        preview = (entry["text"] or "") if entry else ""
        preview = escape(
            preview[:PREVIEW_LENGTH] + ("…" if len(preview) > PREVIEW_LENGTH else "")
        )
        who = await mention(bot, item["chat_id"], t("rem.someone", locale))
        lines.append(
            t(
                "rem.line",
                locale,
                who=who,
                ago=format_waited(item["waited_seconds"], locale),
                preview=preview,
            )
        )
    if len(items) > MAX_LINES:
        lines.append(t("rem.more", locale, count=len(items) - MAX_LINES))
    return "\n".join(lines)


# ------------------------------ оркестрация ---------------------------------


async def process_owner(bot, owner_id: int, now: int | None = None) -> int:
    """Одна проверка владельца. Возвращает число чатов в отправленном напоминании."""
    now = int(now if now is not None else time.time())
    cfg = await get_reminder_settings(owner_id)
    if not cfg or not cfg["enabled"]:
        return 0
    connection = await get_connection_by_owner(owner_id)
    if connection is None:
        return 0

    offset = await get_timezone_offset(owner_id)
    if is_quiet(now, offset, cfg["quiet_start_minutes"], cfg["quiet_end_minutes"]):
        return 0  # отправим на следующей проверке, когда тихие часы закончатся

    items = await find_waiting(
        connection, cfg["hours"] * 3600, now, favorites_only=cfg["favorites_only"]
    )
    if not items:
        return 0

    locale = await get_locale(owner_id)
    text = await render_list(bot, connection, items, locale)
    try:
        await bot.send_message(
            chat_id=connection["owner_chat_id"],
            text=text,
            parse_mode="html",
        )
    except Exception:
        logger.warning(
            "Не удалось отправить напоминание owner=%s", owner_id, exc_info=True
        )
        return 0

    for item in items:
        await log_autoreply(
            owner_id, item["chat_id"], "reminder", str(item["message_id"]), now
        )
    return len(items)


async def run_reminders_loop(bot):
    await asyncio.sleep(60)
    while True:
        try:
            for owner_id in await list_reminder_owner_ids():
                try:
                    await process_owner(bot, owner_id)
                except Exception:
                    logger.exception("Сбой напоминаний owner=%s", owner_id)
        except Exception:
            logger.exception("Сбой цикла напоминаний")
        await asyncio.sleep(LOOP_INTERVAL_SECONDS)


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
        ctx.locale or await get_locale(ctx.connection["owner_id"]),
    )
    await ctx.usage_error(text, parse_mode="html")
