"""Единая точка `report()` и кнопки под сообщением-предупреждением."""

import html
import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.features.alerts import service
from app.features.alerts.catalog import base_code, spec_for
from app.features.alerts.models import Alert
from app.platform.i18n import t
from db.models.user_locale import get_locale

logger = logging.getLogger("bot.alerts")
router = Router()

_PREFIX = "al"


async def report(owner_id: int, code: str, **details) -> None:
    """Сообщить владельцу о проблеме. Не бросает исключений: предупреждение не должно
    ломать то место, откуда его отправили. Не чаще раза в N часов на (owner, code)."""
    try:
        alert = await service.record(owner_id, code, details)
        if alert:
            await _notify(alert)
    except Exception:
        logger.exception("Не удалось зарегистрировать предупреждение %s", code)


def _main_bot():
    from bot_instance import bot  # лениво: bot_instance импортирует роутеры фич

    return bot


def render_text(alert: Alert, locale: str) -> str:
    base = base_code(alert.code)
    details = alert.details
    if spec_for(alert.code).html:  # значения приходят из чужих сообщений: экранируем
        details = {k: html.escape(v, quote=False) for k, v in details.items()}
    return (
        t(f"alert.{base}.title", locale, **details)
        + "\n\n"
        + t(f"alert.{base}.text", locale, **details)
    )


def _message_row(details: dict, locale: str) -> list:
    """«Перейти к сообщению» — как под уведомлениями архива. Нужны `msg_id` (и `username`)."""
    if not str(details.get("msg_id", "")).isdigit():
        return []
    from app.features.archive.bot.keyboards import (
        link_keyboard,
    )  # лениво: цикл импортов

    markup = link_keyboard(
        locale, details.get("username") or None, int(details["msg_id"])
    )
    return markup.inline_keyboard


def _action_rows(code: str, alert_id: int, locale: str) -> list:
    """Кнопки действий под предупреждением (пока — архив заполнен)."""
    if not code.startswith("limit_reached:archive_"):
        return []
    from app.features.archive.bot.limit_actions import action_rows  # лениво: цикл

    return action_rows(code, alert_id, locale)


def keyboard(
    alert_id: int, locale: str, details: dict | None = None, code: str = ""
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *_message_row(details or {}, locale),
            *_action_rows(code, alert_id, locale),
            [
                InlineKeyboardButton(
                    text=t("alert.btn.ok", locale),
                    callback_data=f"{_PREFIX}:ok:{alert_id}",
                ),
                InlineKeyboardButton(
                    text=t("alert.btn.mute", locale),
                    callback_data=f"{_PREFIX}:mute:{alert_id}",
                ),
            ],
        ]
    )


async def _notify(alert: Alert) -> None:
    locale = await get_locale(alert.owner_id)
    try:
        await _main_bot().send_message(
            chat_id=alert.owner_id,
            text=render_text(alert, locale),
            reply_markup=keyboard(alert.id, locale, alert.details, alert.code),
            parse_mode="HTML" if spec_for(alert.code).html else None,
        )
    except Exception as error:  # владелец мог заблокировать бота: это не наша авария
        logger.warning("Предупреждение %s не доставлено: %s", alert.code, error)


@router.callback_query(F.data.startswith(f"{_PREFIX}:"))
async def on_alert_button(call: CallbackQuery) -> None:
    parts = (call.data or "").split(":")
    owner_id = call.from_user.id
    locale = await get_locale(owner_id)
    if len(parts) != 3 or parts[1] not in ("ok", "mute") or not parts[2].isdigit():
        await call.answer()
        return
    alert_id = int(parts[2])
    if parts[1] == "ok":
        await service.dismiss(owner_id, alert_id)
        toast = "alert.toast.ok"
    else:
        await service.mute(owner_id, alert_id)
        toast = "alert.toast.muted"
    await call.answer(t(toast, locale))
    if call.message:
        try:
            await call.message.delete()
        except Exception:
            logger.debug("Не удалось удалить сообщение-предупреждение", exc_info=True)
