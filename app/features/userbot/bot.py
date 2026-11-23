"""Юзербот в чате с ботом: /userbot, согласие, QR, статус, отключение.

Тонкий транспорт над `service`/`login`. Пароль облачного 2FA в чате НЕ принимаем: он
попал бы в историю чата на серверах Telegram; для него кнопка мини-приложения."""

import asyncio
import html
import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    Message,
    WebAppInfo,
)

from app.features.userbot import login, qr, service
from app.platform.i18n import t
from app.platform.tasks import spawn
from config import settings
from db.models.user_locale import get_locale

logger = logging.getLogger("bot.userbot.chat")
router = Router(name="userbot")

POLL = 2  # секунд между проверками состояния входа


def _btn(locale: str, key: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=t(key, locale), callback_data=data)


def _kb(*rows: list[InlineKeyboardButton]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=list(rows))


def _app_row(locale: str) -> list[InlineKeyboardButton]:
    if not settings.WEBAPP_URL:
        return []
    return [
        InlineKeyboardButton(
            text=t("userbot.btn.open_app", locale),
            web_app=WebAppInfo(url=f"{settings.WEBAPP_URL.rstrip('/')}/userbot"),
        )
    ]


def _name(username: str | None) -> str:
    return f" (@{html.escape(username)})" if username else ""


async def _status_view(owner_id: int, locale: str) -> tuple[str, InlineKeyboardMarkup]:
    state = await service.get_status(owner_id)
    if state["reason"]:
        return t(f"userbot.unavailable.{state['reason']}", locale), _kb()
    status = state["status"]
    key = "none" if status == "login" else status
    text = t(f"userbot.status.{key}", locale, name=_name(state["username"]))
    if status in ("none", "revoked", "login"):
        rows = [[_btn(locale, "userbot.btn.connect", "ub:connect")]]
    elif status == "removing":
        rows = []
    else:
        rows = [[_btn(locale, "userbot.btn.off", "ub:off")]]
    rows.append(_app_row(locale))
    return text, _kb(*[r for r in rows if r])


@router.message(Command("userbot"), F.chat.type == "private")
async def cmd_userbot(message: Message):
    locale = await get_locale(message.from_user.id)
    text, markup = await _status_view(message.from_user.id, locale)
    await message.answer(text, reply_markup=markup)


@router.callback_query(F.data == "ub:menu")
async def cb_menu(call: CallbackQuery):
    locale = await get_locale(call.from_user.id)
    text, markup = await _status_view(call.from_user.id, locale)
    await _edit(call.message, text, markup)
    await call.answer()


@router.callback_query(F.data == "ub:connect")
async def cb_connect(call: CallbackQuery):
    locale = await get_locale(call.from_user.id)
    if reason := service.unavailable_reason():
        await call.answer(t(f"userbot.unavailable.{reason}", locale), show_alert=True)
        return
    markup = _kb(
        [_btn(locale, "userbot.btn.agree", "ub:agree")],
        [_btn(locale, "userbot.btn.cancel", "ub:menu")],
    )
    await _edit(call.message, t("userbot.consent", locale), markup)
    await call.answer()


@router.callback_query(F.data == "ub:agree")
async def cb_agree(call: CallbackQuery, bot: Bot):
    owner_id = call.from_user.id
    locale = await get_locale(owner_id)
    if reason := await service.start_login(owner_id):
        await call.answer(t(f"userbot.unavailable.{reason}", locale), show_alert=True)
        return
    await call.answer()
    spawn(
        _follow_login(bot, call.message, owner_id, locale), name=f"ub-chat-{owner_id}"
    )


@router.callback_query(F.data == "ub:cancel")
async def cb_cancel(call: CallbackQuery):
    await login.cancel(call.from_user.id)
    await cb_menu(call)


@router.callback_query(F.data == "ub:off")
async def cb_off(call: CallbackQuery):
    locale = await get_locale(call.from_user.id)
    markup = _kb(
        [_btn(locale, "userbot.btn.off_yes", "ub:off:yes")],
        [_btn(locale, "userbot.btn.cancel", "ub:menu")],
    )
    await _edit(call.message, t("userbot.confirm_off", locale), markup)
    await call.answer()


@router.callback_query(F.data == "ub:off:yes")
async def cb_off_yes(call: CallbackQuery):
    locale = await get_locale(call.from_user.id)
    await call.answer()
    await service.disconnect(call.from_user.id)
    text, markup = await _status_view(call.from_user.id, locale)
    await _edit(call.message, t("userbot.off_done", locale) + "\n\n" + text, markup)


async def _edit(message: Message, text: str, markup) -> None:
    """Экран заменяется на месте; сообщение с QR (фото) пересоздаётся."""
    try:
        if message.photo:
            await message.delete()
            await message.answer(text, reply_markup=markup)
        else:
            await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest as exc:
        if "not modified" not in str(exc):
            raise


async def _qr_markup(locale: str, url: str, with_link: bool) -> InlineKeyboardMarkup:
    rows = []
    if with_link:
        rows.append([InlineKeyboardButton(text=t("userbot.qr.link", locale), url=url)])
    rows.append([_btn(locale, "userbot.btn.cancel", "ub:cancel")])
    return _kb(*rows)


async def _show_qr(bot: Bot, message: Message, locale: str, url: str) -> Message:
    """QR-картинка. Кнопка-ссылка tg://login не всегда принимается Bot API: тогда без неё."""
    png = await asyncio.to_thread(qr.render_png, url)
    photo = BufferedInputFile(png, filename="qr.png")
    caption = t("userbot.qr.caption", locale)
    for with_link in (True, False):
        markup = await _qr_markup(locale, url, with_link)
        try:
            if message.photo:
                media = InputMediaPhoto(media=photo, caption=caption)
                return await bot.edit_message_media(
                    media,
                    chat_id=message.chat.id,
                    message_id=message.message_id,
                    reply_markup=markup,
                )
            await message.delete()
            return await bot.send_photo(
                message.chat.id, photo, caption=caption, reply_markup=markup
            )
        except TelegramBadRequest:
            if not with_link:
                raise
    raise RuntimeError("unreachable")


async def _follow_login(bot: Bot, message: Message, owner_id: int, locale: str) -> None:
    """Обновляет сообщение, пока идёт вход: QR, затем итог."""
    shown = 0
    try:
        while True:
            flow = login.get(owner_id)
            if flow is None:
                return
            if flow.state == login.QR and flow.qr_version != shown:
                shown = flow.qr_version
                message = await _show_qr(bot, message, locale, flow.qr_url)
            elif flow.state == login.PASSWORD:
                markup = _kb(_app_row(locale)) if _app_row(locale) else None
                await _edit(message, t("userbot.password", locale), markup)
                shown = -1
            elif flow.state in (login.DONE, login.ERROR):
                await _finish(message, owner_id, locale, flow)
                return
            await asyncio.sleep(POLL)
    except Exception:
        logger.exception("Не удалось показать ход входа юзербота")


async def _finish(message: Message, owner_id: int, locale: str, flow) -> None:
    if flow.state == login.DONE:
        info = (await service.get_status(owner_id))["username"]
        text = t("userbot.done", locale, name=_name(info))
    else:
        text = t(f"userbot.error.{flow.error}", locale)
    status_text, markup = await _status_view(owner_id, locale)
    await _edit(message, text + "\n\n" + status_text, markup)
