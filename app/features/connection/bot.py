import json
import logging

from aiogram import Bot, Router
from aiogram.types import BusinessConnection

from db.models.connection import get_connection, upsert_connection
from db.models.user_locale import get_locale
from app.features.connection.service import adopt_previous_connection
from app.platform.i18n import t
from app.platform.telegram.webapp import webapp_keyboard
from app.platform.utils import log_suppressed

logger = logging.getLogger("bot.connection")
router = Router(name="connection")


@router.business_connection()
async def on_business_connection(connection: BusinessConnection, bot: Bot):
    previous = await get_connection(connection.id)
    rights = connection.rights.model_dump(mode="json") if connection.rights else {}

    await upsert_connection(
        connection_id=connection.id,
        owner_id=connection.user.id,
        owner_chat_id=connection.user_chat_id,
        is_enabled=connection.is_enabled,
        owner_name=connection.user.full_name,
        owner_username=connection.user.username,
        rights_json=json.dumps(rights, ensure_ascii=False),
    )

    if previous is None and connection.is_enabled:
        # новое подключение (например, после переподключения бота в настройках
        # Telegram): переносим данные со старого, чтобы архив и настройки не пропали
        try:
            await adopt_previous_connection(connection.id, connection.user.id)
        except Exception:
            logger.exception("Не удалось перенести данные на новое подключение")

    was_enabled = bool(previous and previous["is_enabled"])
    if connection.is_enabled == was_enabled:
        return

    locale = await get_locale(connection.user.id)

    if connection.is_enabled:
        try:
            await bot.send_message(
                chat_id=connection.user_chat_id,
                text=t("connection.connected_notice", locale),
                reply_markup=webapp_keyboard(t("connection.open_app_button", locale)),
            )
        except Exception:
            log_suppressed("app/features/connection/bot.py:41")
    else:
        try:
            await bot.send_message(
                chat_id=connection.user_chat_id,
                text=t("connection.disconnected_notice", locale),
            )
        except Exception:
            log_suppressed("app/features/connection/bot.py:49")
