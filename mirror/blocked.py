"""Отслеживает блокировку/удаление зеркального бота из чата вне активной
рассылки (во время рассылки это ловит TelegramForbiddenError прямо в
mirror/spam.py — см. там)."""

from aiogram import Bot, Router
from aiogram.types import ChatMemberUpdated
from core.utils import log_suppressed

router = Router(name="mirror_blocked")

_NOTIFIED_STATUSES = {"kicked", "left"}


@router.my_chat_member()
async def on_mirror_membership_changed(
    event: ChatMemberUpdated, bot: Bot, owner_id: int
):
    if event.new_chat_member.status not in _NOTIFIED_STATUSES:
        return

    chat_title = event.chat.title or event.chat.full_name or str(event.chat.id)
    try:
        await bot.send_message(
            chat_id=owner_id,
            text=f"⚠️ Зеркало убрали/заблокировали в чате «{chat_title}».",
        )
    except Exception:
        log_suppressed("mirror/blocked.py:26")
