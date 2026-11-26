"""Кнопки под оповещением (`ops:`) и команда /status. Админ проверяется на КАЖДОМ нажатии."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.features.limits.plans import admin_ids
from app.features.ops import notify, service
from app.features.ops.models import ErrorEvent
from app.platform.i18n import t
from db.models.user_locale import get_locale

router = Router(name="ops")


def _is_admin(user) -> bool:
    return bool(user and user.id in admin_ids())


@router.callback_query(F.data.startswith("ops:"))
async def on_button(cq: CallbackQuery) -> None:
    locale = await get_locale(cq.from_user.id)
    if not _is_admin(cq.from_user):
        await cq.answer(t("ops.cb.denied", locale), show_alert=True)
        return
    try:
        _, action, raw_id = cq.data.split(":")
        event_id = int(raw_id)
    except ValueError:
        await cq.answer()
        return
    now = notify.now_ts()
    row = await ErrorEvent.get_or_none(id=event_id)
    if row is None:
        await cq.answer(t("ops.cb.gone", locale), show_alert=True)
        return
    if action == "ok":
        await service.acknowledge(event_id, now)
        await cq.answer(t("ops.cb.ok", locale))
    elif action == "mute":
        await service.mute(event_id, now)
        await cq.answer(t("ops.cb.mute", locale))
    elif action == "info" and cq.message:
        await cq.message.edit_text(
            notify.render_details(row, locale),
            parse_mode="html",
            reply_markup=notify.keyboard(event_id, locale, details=True),
        )
        await cq.answer()
    else:
        await cq.answer()


@router.message(
    Command("status"), F.chat.type == "private", F.from_user.func(_is_admin)
)
async def on_status(message: Message) -> None:
    await message.answer(
        await notify.status_message(message.from_user.id), parse_mode="html"
    )
