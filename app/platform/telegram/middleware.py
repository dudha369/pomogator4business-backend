"""Логирует КАЖДЫЙ входящий апдейт от Telegram — даже если для него не
нашлось ни одного хендлера — и время его обработки. Регистрируется как
outer middleware на dp.update в bot_instance.setup_routes(), поэтому видит
буквально всё до того, как роутеры начнут решать, кому его передать.
"""

import logging
import time

from aiogram import BaseMiddleware
from aiogram.types import Update

logger = logging.getLogger("bot.updates")


def _size(text) -> int:
    """В логи (Render) попадает только длина: текст личных сообщений там не место."""
    return len(text) if text else 0


def _describe(update: Update) -> str:
    if update.business_message:
        m = update.business_message
        return (
            f"business_message conn={m.business_connection_id} chat={m.chat.id} "
            f"from={m.from_user.id if m.from_user else '?'} text_len={_size(m.text or m.caption)}"
        )
    if update.edited_business_message:
        m = update.edited_business_message
        return (
            f"edited_business_message conn={m.business_connection_id} "
            f"chat={m.chat.id} msg_id={m.message_id}"
        )
    if update.deleted_business_messages:
        e = update.deleted_business_messages
        return (
            f"deleted_business_messages conn={e.business_connection_id} "
            f"chat={e.chat.id} count={len(e.message_ids)}"
        )
    if update.business_connection:
        c = update.business_connection
        return f"business_connection id={c.id} owner={c.user.id} enabled={c.is_enabled}"
    if update.message:
        m = update.message
        return (
            f"message chat={m.chat.id} from={m.from_user.id if m.from_user else '?'} "
            f"text_len={_size(m.text)}"
        )
    if update.callback_query:
        cq = update.callback_query
        return f"callback_query from={cq.from_user.id} data={cq.data!r}"
    if update.my_chat_member:
        cm = update.my_chat_member
        return f"my_chat_member chat={cm.chat.id} status={cm.new_chat_member.status}"
    return f"update type={update.event_type}"


class UpdateLoggingMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data):
        summary = _describe(event)
        started = time.monotonic()
        logger.info("→ %s", summary)

        try:
            result = await handler(event, data)
        except Exception:
            duration_ms = (time.monotonic() - started) * 1000
            logger.exception("✗ %s (%.0f ms)", summary, duration_ms)
            raise

        duration_ms = (time.monotonic() - started) * 1000
        logger.info("✓ %s (%.0f ms)", summary, duration_ms)
        return result
