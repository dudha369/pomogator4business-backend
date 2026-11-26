"""Отправка оповещений администраторам (ADMIN_USER_IDS) основным ботом."""

import html
import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.limits.plans import admin_ids
from app.features.ops import service
from app.features.ops.models import ErrorEvent
from app.platform.i18n import t
from db.models.user_locale import get_locale

logger = logging.getLogger("bot.ops")

Render = Callable[[str], tuple[str, InlineKeyboardMarkup | None]]


def _bot():
    from bot_instance import bot  # лениво: bot_instance импортирует роутеры фич

    return bot


def fmt_time(ts: int | None) -> str:
    if not ts:
        return "—"
    return datetime.fromtimestamp(ts, UTC).strftime("%d.%m %H:%M")


def esc(value) -> str:
    return html.escape(str(value), quote=False)


async def _locale(user_id: int) -> str:
    try:
        return await get_locale(user_id)
    except Exception:  # БД может быть недоступна: тогда русский
        return "ru"


async def send_to_admins(render: Render, *, silent: bool = False) -> int:
    """Рассылает всем администраторам, текст — на языке каждого. Не бросает."""
    sent = 0
    for user_id in sorted(admin_ids()):
        locale = await _locale(user_id)
        text, markup = render(locale)
        try:
            await _bot().send_message(
                chat_id=user_id,
                text=text,
                parse_mode="html",
                reply_markup=markup,
                disable_notification=silent,
            )
            sent += 1
        except (
            Exception
        ) as exc:  # без exc_info: текст ошибки Telegram не нужен в журнале
            logger.warning(
                "Оповещение администратору %s не доставлено: %s",
                user_id,
                type(exc).__name__,
            )
    return sent


def keyboard(
    event_id: int, locale: str, *, details: bool = False
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=t("ops.btn.ok", locale), callback_data=f"ops:ok:{event_id}"
            ),
            InlineKeyboardButton(
                text=t("ops.btn.mute", locale), callback_data=f"ops:mute:{event_id}"
            ),
        ]
    ]
    if not details:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("ops.btn.info", locale), callback_data=f"ops:info:{event_id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_event(row: ErrorEvent, kind: str, since: int, locale: str) -> str:
    critical = "_critical" if row.severity == 1 else ""
    title = t(f"ops.title.{kind}{critical}", locale, component=esc(row.component))
    body = t(
        "ops.event.body",
        locale,
        kind=esc(row.kind),
        place=esc(row.place),
        count=row.count,
        first=fmt_time(row.first_at),
        last=fmt_time(row.last_at),
        build=esc(row.last_build or "?"),
    )
    extra = t("ops.event.since", locale, since=since) if kind == "repeat" else ""
    return f"{title}\n{body}{extra}"


def render_details(row: ErrorEvent, locale: str) -> str:
    return (
        render_event(row, "repeat" if row.notified_at else "new", 0, locale)
        + "\n\n"
        + t(
            "ops.details",
            locale,
            sample=esc(row.sample),
            first_build=esc(row.first_build or "?"),
        )
    )


async def dispatch(decisions: list[service.Decision], burst: bool, now: int) -> None:
    th = service.throttle
    if burst:
        top = await service.top_recent(now)
        total = sum(c for _, c in th.events)

        def render_burst(locale: str):
            lines = "\n".join(
                f"• {esc(r.component)} · {esc(r.kind)} · {esc(r.place)} — {r.count}"
                for r in top
            )
            text = t(
                "ops.burst",
                locale,
                n=total,
                top=lines,
                minutes=service.BURST_PAUSE // 60,
            )
            return text, None

        await send_to_admins(render_burst)
    for d in decisions:
        critical = d.row.severity == 1
        if not th.allow(critical, now):
            continue
        hidden = th.take_hidden()

        def render(locale: str, d=d, hidden=hidden):
            text = render_event(d.row, d.kind, d.since, locale)
            if hidden:
                text += "\n\n" + t("ops.hidden", locale, n=hidden)
            return text, keyboard(d.row.id, locale)

        if await send_to_admins(render):
            th.mark_sent(critical, now)
            await service.mark_notified(d.row, now)


async def db_unreachable() -> None:
    await send_to_admins(lambda locale: (t("ops.db_unreachable", locale), None))


async def status_message(user_id: int) -> str:
    from app.features.ops import health

    report = await health.collect()
    return health.render_text(report, await _locale(user_id))


def now_ts() -> int:
    return int(time.time())
