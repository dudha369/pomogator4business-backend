"""Единая точка `report()` и кнопки под сообщением-предупреждением."""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from app.features.alerts import service
from app.features.alerts.catalog import base_code
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
    return (
        t(f"alert.{base}.title", locale, **alert.details)
        + "\n\n"
        + t(f"alert.{base}.text", locale, **alert.details)
    )


def keyboard(alert_id: int, locale: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("alert.btn.ok", locale),
                    callback_data=f"{_PREFIX}:ok:{alert_id}",
                ),
                InlineKeyboardButton(
                    text=t("alert.btn.mute", locale),
                    callback_data=f"{_PREFIX}:mute:{alert_id}",
                ),
            ]
        ]
    )


async def _notify(alert: Alert) -> None:
    locale = await get_locale(alert.owner_id)
    try:
        await _main_bot().send_message(
            chat_id=alert.owner_id,
            text=render_text(alert, locale),
            reply_markup=keyboard(alert.id, locale),
            parse_mode=None,
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
