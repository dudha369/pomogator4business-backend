"""Кнопки под уведомлениями архива."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from app.features.archive.render.classic import forward_link, user_link
from app.features.archive.service import gift_summary
from app.features.archive.snapshot import GIFT_KINDS
from app.platform.i18n import t

ICON_DELETED = "5258389041006518073"  # коробка: «сообщение в архиве»
ICON_TRASH = "5258130763148172425"  # мусорка — только для «Удалить у себя»
ICON_GIFT = "5963213811597970978"
ICON_USER = "5260399854500191689"
ICON_FORWARD = "5260450573768990626"
ICON_OPEN = "5260730055880876557"


def link_keyboard(locale, username, message_id):
    """«Перейти к сообщению»: ссылка, если есть username, иначе тост."""
    label = t("archive.open_message_button", locale)
    if username:
        button = InlineKeyboardButton(
            text=label,
            url=f"https://t.me/{username}/{message_id}",
            icon_custom_emoji_id=ICON_OPEN,
        )
    else:
        button = InlineKeyboardButton(
            text=label,
            icon_custom_emoji_id=ICON_OPEN,
            callback_data="archive:link_unavailable",
        )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


def delete_keyboard(locale, callback="archive:delete_notice"):
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t("archive.delete_notice_button", locale),
                    icon_custom_emoji_id=ICON_TRASH,
                    style="danger",
                    callback_data=callback,
                )
            ]
        ]
    )


def sender_keyboard(locale, sender, snap, *, profile=True, own=False):
    """Кнопки под содержимым, к которому нельзя дописать подпись (стикер, кружок,
    геолокация, контакт, подарок). Сверху серая «заглушка» со статусом, ниже цветные
    рабочие кнопки: профиль и «переслано от» (синие), «Удалить у себя» (красная)."""
    rows = [
        [
            InlineKeyboardButton(
                text=t(
                    "archive.btn_deleted_own" if own else "archive.btn_deleted", locale
                ),
                icon_custom_emoji_id=ICON_DELETED,
                callback_data="archive:info",
            )
        ]
    ]
    if snap.get("kind") in GIFT_KINDS and gift_summary(snap):
        rows.append(
            [
                InlineKeyboardButton(
                    text=gift_summary(snap),
                    icon_custom_emoji_id=ICON_GIFT,
                    callback_data="archive:info",
                )
            ]
        )
    link = user_link(sender.get("id"), sender.get("username"))
    if profile and link:
        name = sender.get("name") or "—"
        rows.append(
            [
                InlineKeyboardButton(
                    text=t("archive.btn_sender", locale, name=name),
                    icon_custom_emoji_id=ICON_USER,
                    style="primary",
                    url=link,
                )
            ]
        )
    forward = snap.get("forward")
    if forward:
        label = t(
            "archive.btn_forwarded",
            locale,
            name=forward.get("name") or forward.get("signature") or "—",
        )
        href = forward_link(forward)
        if href:
            button = InlineKeyboardButton(
                text=label,
                icon_custom_emoji_id=ICON_FORWARD,
                style="primary",
                url=href,
            )
        else:
            button = InlineKeyboardButton(
                text=label,
                icon_custom_emoji_id=ICON_FORWARD,
                callback_data="archive:info",
            )
        rows.append([button])
    rows.append(delete_keyboard(locale).inline_keyboard[0])
    return InlineKeyboardMarkup(inline_keyboard=rows)
