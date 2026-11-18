"""Кнопки под уведомлениями архива."""

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.platform.i18n import t
from app.platform.utils import log_suppressed
from db.models.user_locale import get_locale

router = Router(name="archive_callbacks")


@router.callback_query(F.data == "archive:link_unavailable")
async def on_link_unavailable(call: CallbackQuery):
    locale = await get_locale(call.from_user.id)
    await call.answer(t("archive.link_unavailable", locale), show_alert=True)


@router.callback_query(F.data == "archive:delete_notice")
async def on_delete_notice(call: CallbackQuery):
    try:
        await call.message.delete()
    except Exception:
        log_suppressed("archive/bot/callbacks.py:delete_notice", benign=True)
    await call.answer()


@router.callback_query(F.data == "archive:delete_pair")
async def on_delete_pair(call: CallbackQuery):
    for msg in (call.message, getattr(call.message, "reply_to_message", None)):
        if msg is None:
            continue
        try:
            await msg.delete()
        except Exception:
            log_suppressed("archive/bot/callbacks.py:delete_pair", benign=True)
    await call.answer()


@router.callback_query(F.data == "archive:info")
async def on_info(call: CallbackQuery):
    locale = await get_locale(call.from_user.id)
    await call.answer(t("archive.toast_deleted", locale))
