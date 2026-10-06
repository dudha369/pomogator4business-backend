"""Общая кнопка на мини-приложение — используется и в уведомлении о
подключении (handlers/connection.py), и в /start (handlers/settings.py)."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

from config import settings


def webapp_keyboard(button_text: str) -> InlineKeyboardMarkup | None:
    if not settings.WEBAPP_URL:
        return None
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=button_text,
                    icon_custom_emoji_id="5260233433107407649",
                    web_app=WebAppInfo(url=settings.WEBAPP_URL),
                )
            ]
        ]
    )
