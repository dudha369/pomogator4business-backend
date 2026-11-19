"""Кнопки «Отправить» / «Отклонить» под черновиком ИИ-ответа."""

import logging
import time

from aiogram import Bot, F, Router
from aiogram.types import CallbackQuery

from app.features.ai.queries import (
    create_draft,
    get_draft,
    set_draft_status,
    set_draft_status_force,
)
from app.features.ai.service import DRAFT_TTL_SECONDS
from app.features.autoresponder.queries import (
    log_autoreply,
)
from app.features.history.service import log_message
from app.platform.i18n import t
from db.models.connection import get_connection_by_owner
from db.models.user_locale import get_locale

# ------------------------------ черновики -----------------------------------


def draft_keyboard(draft_id: int, locale: str):
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    from app.platform.i18n import t

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("ai.btn_send", locale), callback_data=f"aid:send:{draft_id}"
                ),
                InlineKeyboardButton(
                    text=t("ai.btn_dismiss", locale), callback_data=f"aid:no:{draft_id}"
                ),
            ]
        ]
    )


async def notify_draft(
    bot, connection, contact_name, incoming_text, draft_id, reply_text
):
    """Присылает владельцу в личку черновик ответа с кнопками."""
    from app.platform.i18n import t

    locale = await get_locale(connection["owner_id"])
    text = "\n\n".join(
        [
            t("ai.draft_header", locale, name=contact_name or "?"),
            t("ai.draft_incoming", locale) + "\n" + incoming_text[:500],
            t("ai.draft_reply", locale) + "\n" + reply_text[:3000],
        ]
    )
    await bot.send_message(
        chat_id=connection["owner_chat_id"],
        text=text,
        reply_markup=draft_keyboard(draft_id, locale),
    )


async def deliver_reply(bot, connection, ai_settings, message, text, reply_text, now):
    """Отправляет ответ (auto) или создаёт черновик (draft). Возвращает True,
    если что-то сделано."""
    owner_id, chat_id = connection["owner_id"], message.chat.id

    if ai_settings["mode"] == "auto":
        sent = await bot.send_message(
            business_connection_id=connection["connection_id"],
            chat_id=chat_id,
            text=reply_text,
        )
        await log_message(connection["connection_id"], chat_id, sent.message_id)
    else:
        draft_id = await create_draft(
            owner_id, chat_id, message.message_id, reply_text, now
        )
        name = getattr(message.chat, "full_name", None) or getattr(
            message.from_user, "full_name", None
        )
        await notify_draft(bot, connection, name, text, draft_id, reply_text)

    # считаем и черновики: каждый — это платный запрос к провайдеру
    await log_autoreply(owner_id, chat_id, "ai", None, now)
    return True


logger = logging.getLogger("bot.ai_drafts")
router = Router(name="ai_drafts")


async def _finish(callback: CallbackQuery, suffix: str):
    """Убирает кнопки и дописывает итог к тексту черновика."""
    try:
        await callback.message.edit_text(
            f"{callback.message.text}\n\n{suffix}", reply_markup=None
        )
    except Exception:
        logger.debug("Не удалось обновить сообщение с черновиком", exc_info=True)


@router.callback_query(F.data.startswith("aid:"))
async def on_draft_button(callback: CallbackQuery, bot: Bot):
    try:
        _, action, raw_id = callback.data.split(":", 2)
        draft_id = int(raw_id)
    except ValueError:
        await callback.answer()
        return

    draft = await get_draft(draft_id)
    locale = await get_locale(callback.from_user.id)
    if draft is None or draft["owner_id"] != callback.from_user.id:
        await callback.answer(t("ai.not_yours", locale), show_alert=True)
        return

    if action == "no":
        if await set_draft_status(draft_id, "dismissed"):
            await _finish(callback, t("ai.dismissed", locale))
            await callback.answer()
        else:
            await callback.answer(t("ai.already", locale), show_alert=True)
        return

    if action != "send":
        await callback.answer()
        return

    if time.time() - draft["created_at"] > DRAFT_TTL_SECONDS:
        await set_draft_status(draft_id, "dismissed")
        await _finish(callback, t("ai.expired", locale))
        await callback.answer(t("ai.expired", locale), show_alert=True)
        return

    connection = await get_connection_by_owner(draft["owner_id"])
    if connection is None:
        await callback.answer(t("ai.not_connected", locale), show_alert=True)
        return

    # pending → sent атомарно: двойное нажатие не отправит ответ дважды
    if not await set_draft_status(draft_id, "sent"):
        await callback.answer(t("ai.already", locale), show_alert=True)
        return

    try:
        sent = await bot.send_message(
            business_connection_id=connection["connection_id"],
            chat_id=draft["chat_id"],
            text=draft["text"],
        )
    except Exception:
        logger.warning("Не удалось отправить черновик %s", draft_id, exc_info=True)
        await set_draft_status_force(draft_id, "pending")
        await callback.answer(t("ai.send_failed", locale), show_alert=True)
        return

    await log_message(connection["connection_id"], draft["chat_id"], sent.message_id)
    await _finish(callback, t("ai.sent", locale))
    await callback.answer()
