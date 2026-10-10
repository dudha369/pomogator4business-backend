from aiogram.types import Message

from core.i18n import t
from core.registry import registry
from core import database as db
from core.utils import log_suppressed

registry.register_passive_module("scam")

_SERVICES = ["SafeBase", "Metka RO", "GID Anti-Scam", "TonTake Scammers", "SYNDICATE"]


async def _check_safebase(user_id):
    return None


async def _check_metka_ro(user_id):
    return None


async def _check_gid(user_id):
    return None


async def _check_tontake(user_id):
    return None


async def _check_syndicate(user_id):
    return None


_CHECKERS = {
    "SafeBase": _check_safebase,
    "Metka RO": _check_metka_ro,
    "GID Anti-Scam": _check_gid,
    "TonTake Scammers": _check_tontake,
    "SYNDICATE": _check_syndicate,
}


async def _run_checks(user_id, locale):
    results = {}
    for name in _SERVICES:
        checker = _CHECKERS[name]
        try:
            result = await checker(user_id)
        except Exception:
            result = None
        results[name] = (
            result if result is not None else t("scam.api_not_connected", locale)
        )
    return results


def _format_profile(locale, user):
    lines = [
        t("scam.new_contact", locale, name=user.full_name),
        t("scam.id_label", locale, id=user.id),
    ]
    if user.username:
        lines.append(t("scam.username_label", locale, username=user.username))
    return "\n".join(lines)


def _format_checks(locale, results):
    lines = [t("scam.checks_header", locale)]
    for name, status in results.items():
        lines.append(t("scam.check_line", locale, name=name, status=status))
    return "\n".join(lines)


async def handle_new_contact(bot, connection, message: Message):
    user = message.from_user
    if user is None:
        return

    chat_id = message.chat.id
    owner_id = connection["owner_id"]
    connection_id = connection["connection_id"]

    if await db.is_known_chat(owner_id, chat_id):
        return

    # known_chats — отдельный кэш; если он вдруг пуст не из-за реально
    # нового контакта (например, таблицу пересоздавали при миграции), это
    # не должно превращаться в ложную тревогу для людей, с которыми
    # переписка идёт уже давно. Проверяем по факту — есть ли в истории
    # хоть одно сообщение, кроме текущего.
    if await db.has_other_messages(connection_id, chat_id, message.message_id):
        await db.mark_known_chat(owner_id, chat_id)
        return

    await db.mark_known_chat(owner_id, chat_id)

    locale = await db.get_locale(owner_id)
    results = await _run_checks(user.id, locale)
    text = _format_profile(locale, user) + "\n\n" + _format_checks(locale, results)

    try:
        await bot.send_message(chat_id=connection["owner_chat_id"], text=text)
    except Exception:
        log_suppressed("modules/scam.py:101")
