import json

from aiogram import Bot, Router
from aiogram.types import BusinessConnection

from core import database as db
from core.i18n import t
from core.webapp import webapp_keyboard
from core.utils import log_suppressed

router = Router(name="connection")


@router.business_connection()
async def on_business_connection(connection: BusinessConnection, bot: Bot):
    previous = await db.get_connection(connection.id)
    rights = connection.rights.model_dump(mode="json") if connection.rights else {}

    await db.upsert_connection(
        connection_id=connection.id,
        owner_id=connection.user.id,
        owner_chat_id=connection.user_chat_id,
        is_enabled=connection.is_enabled,
        owner_name=connection.user.full_name,
        owner_username=connection.user.username,
        rights_json=json.dumps(rights, ensure_ascii=False),
    )

    was_enabled = bool(previous and previous["is_enabled"])
    if connection.is_enabled == was_enabled:
        return

    locale = await db.get_locale(connection.user.id)

    if connection.is_enabled:
        try:
            await bot.send_message(
                chat_id=connection.user_chat_id,
                text=t("connection.connected_notice", locale),
                reply_markup=webapp_keyboard(t("connection.open_app_button", locale)),
            )
        except Exception:
            log_suppressed("handlers/connection.py:41")
    else:
        try:
            await bot.send_message(
                chat_id=connection.user_chat_id,
                text=t("connection.disconnected_notice", locale),
            )
        except Exception:
            log_suppressed("handlers/connection.py:49")
