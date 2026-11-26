"""Кнопки под предупреждением «архив заполнен»: выбрать, удалить файлы, удалить всё."""

import logging

from aiogram import F, Router
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    WebAppInfo,
)

from app.features.alerts import service as alerts
from app.features.archive import capacity
from app.features.archive.queries import archive_usage, delete_entries, newest_log_id
from app.features.limits.plans import MB
from app.platform.i18n import t
from config import settings
from db.models.user_locale import get_locale

logger = logging.getLogger("bot.archive.limit")
router = Router(name="archive_limit_actions")

_PREFIX = "arl"
ARCHIVE_METRICS = ("archive_entries", "archive_media_bytes")


def action_rows(code: str, alert_id: int, locale: str) -> list[list]:
    """Строки кнопок для alert `limit_reached:<metric>` (пусто для других кодов)."""
    metric = code.partition(":")[2]
    if metric not in ARCHIVE_METRICS:
        return []

    def button(key: str, action: str) -> list[InlineKeyboardButton]:
        return [
            InlineKeyboardButton(
                text=t(f"archive.limit.{key}", locale),
                callback_data=f"{_PREFIX}:{action}:{alert_id}",
            )
        ]

    url = f"{settings.WEBAPP_URL.rstrip('/')}/archive?select=1"
    rows = [
        [
            InlineKeyboardButton(
                text=t("archive.limit.select", locale), web_app=WebAppInfo(url=url)
            )
        ],
        button("files", "files"),
    ]
    if metric == "archive_entries":
        rows.append(button("all", "all"))
    return rows


def _confirm_markup(locale: str, alert_id: int, count: int, newest: int):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("archive.limit.yes", locale, count=count),
                    callback_data=f"{_PREFIX}:yes:{alert_id}:{newest}",
                ),
                InlineKeyboardButton(
                    text=t("archive.limit.no", locale),
                    callback_data=f"{_PREFIX}:no:{alert_id}",
                ),
            ]
        ]
    )


@router.callback_query(F.data.startswith(f"{_PREFIX}:"))
async def on_limit_button(call: CallbackQuery) -> None:
    parts = (call.data or "").split(":")
    owner_id = call.from_user.id
    locale = await get_locale(owner_id)
    # files/all/no: arl:<действие>:<alert>; yes: arl:yes:<alert>:<граница id>
    shape = {"files": 3, "all": 3, "no": 3, "yes": 4}.get(
        parts[1] if len(parts) > 1 else ""
    )
    if shape != len(parts) or not all(p.isdigit() for p in parts[2:]):
        await call.answer()
        return
    action, alert_id = parts[1], int(parts[2])
    connection_ids = await capacity.owner_connection_ids(owner_id)
    try:
        if action == "files":
            count, freed = await delete_entries(connection_ids, media_only=True)
            text = t("archive.limit.files_done", locale, count=count, size=freed // MB)
            await _finish(call, owner_id, alert_id, text)
        elif action == "all":
            count, _ = await archive_usage(connection_ids)
            newest = await newest_log_id(connection_ids)
            if not count or newest is None:
                await _finish(
                    call, owner_id, alert_id, t("archive.limit.nothing", locale)
                )
                return
            await call.message.edit_text(
                t("archive.limit.confirm", locale, count=count),
                reply_markup=_confirm_markup(locale, alert_id, count, newest),
            )
            await call.answer()
        elif action == "yes":
            count, _ = await delete_entries(connection_ids, max_id=int(parts[3]))
            text = t("archive.limit.all_done", locale, count=count)
            await _finish(call, owner_id, alert_id, text)
        else:  # no: убираем вопрос, предупреждение остаётся в мини-приложении
            await call.answer()
            await call.message.delete()
    except Exception:
        logger.exception("Кнопка предупреждения архива не сработала: %s", action)
        await call.answer(t("archive.limit.failed", locale), show_alert=True)


async def _finish(call: CallbackQuery, owner_id: int, alert_id: int, text: str):
    """Результат вместо предупреждения; само предупреждение закрываем."""
    await alerts.dismiss(owner_id, alert_id)
    await call.answer()
    await call.message.edit_text(text, reply_markup=None)
