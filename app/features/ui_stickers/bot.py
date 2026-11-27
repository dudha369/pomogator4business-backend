"""Служебная команда администратора: пришли стикер или премиум-эмодзи — получи
строку для реестра `app/platform/ui_stickers.py`. Остальным бот не отвечает."""

from aiogram import Router
from aiogram.types import Message

from app.features.limits.plans import admin_ids
from app.platform.i18n import t
from db.models.user_locale import get_locale

router = Router(name="ui_stickers")


def _custom_emoji_ids(message: Message) -> list[str]:
    entities = message.entities or []
    return [e.custom_emoji_id for e in entities if e.type == "custom_emoji"]


def _wanted(message: Message) -> bool:
    """Личка, администратор, и в сообщении есть что описывать."""
    return bool(
        message.chat.type == "private"
        and message.from_user
        and message.from_user.id in admin_ids()
        and (message.sticker or _custom_emoji_ids(message))
    )


def describe(message: Message, locale: str) -> str:
    """Текст ответа: тип, идентификаторы и готовая строка реестра."""
    lines = []
    if message.sticker:
        s = message.sticker
        if s.custom_emoji_id:
            lines.append(t("ui_stickers.emoji", locale, id=s.custom_emoji_id))
        elif s.set_name:
            lines.append(
                t("ui_stickers.sticker", locale, set=s.set_name, uid=s.file_unique_id)
            )
        else:
            lines.append(t("ui_stickers.no_set", locale))
    for emoji_id in _custom_emoji_ids(message):
        lines.append(t("ui_stickers.emoji", locale, id=emoji_id))
    return "\n\n".join(lines)


@router.message(_wanted)
async def on_sticker(message: Message) -> None:
    locale = await get_locale(message.from_user.id)
    await message.answer(describe(message, locale), parse_mode="html")
