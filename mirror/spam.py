import asyncio

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import Message

from core.spam_control import clamp, is_spam_active, start_spam, stop_spam
from core.utils import log_suppressed

router = Router(name="mirror_spam")

_MAX_COUNT = 5000
_MIN_DELAY = 0.1
_MAX_DELAY = 60
_DEFAULT_STEP_DELAY = 0.15


async def _notify_owner(bot: Bot, owner_id: int, text: str) -> None:
    try:
        await bot.send_message(chat_id=owner_id, text=text)
    except Exception:
        log_suppressed("mirror/spam.py:20")


def _clamp_notice(requested: int, count: int) -> str:
    return (
        f"Запрошено {requested}, но лимит зеркала — {_MAX_COUNT}. "
        f"Отправляю {count}."
    )


async def _send_sequence(
    bot: Bot, owner_id: int, chat_id: int, items, delay: float
) -> None:
    """items — список того, что отправлять по одному сообщению за раз."""
    if is_spam_active(f"mirror:{owner_id}"):
        await _notify_owner(
            bot, owner_id, "Рассылка уже идёт, дождитесь её завершения."
        )
        return

    start_spam(f"mirror:{owner_id}")
    try:
        for item in items:
            try:
                await bot.send_message(chat_id=chat_id, text=item)
            except TelegramForbiddenError:
                await _notify_owner(
                    bot,
                    owner_id,
                    "⚠️ Зеркало заблокировано в этом чате (или бота удалили из чата) "
                    "— рассылка остановлена.",
                )
                return
            except Exception:
                continue
            await asyncio.sleep(delay)
    finally:
        stop_spam(f"mirror:{owner_id}")


@router.message(F.text.regexp(r"^\.spam(\s|$)"))
async def cmd_spam(message: Message, bot: Bot, owner_id: int):
    if message.from_user.id != owner_id:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3 or not parts[1].isdigit():
        await message.answer("Формат: .spam [кол-во] [текст]\nПример: .spam 10 Привет")
        return

    requested = int(parts[1])
    text = parts[2]
    if requested <= 0:
        return

    count = clamp(requested, _MAX_COUNT)
    if count < requested:
        await _notify_owner(bot, owner_id, _clamp_notice(requested, count))

    await _send_sequence(bot, owner_id, message.chat.id, [text] * count, 0.05)


@router.message(F.text.regexp(r"^\.dspam(\s|$)"))
async def cmd_dspam(message: Message, bot: Bot, owner_id: int):
    if message.from_user.id != owner_id:
        return

    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer(
            "Формат: .dspam [задержка] [кол-во] [текст]\nПример: .dspam 2 10 Привет"
        )
        return

    try:
        delay = float(parts[1])
    except ValueError:
        await message.answer("Задержка должна быть числом от 0.1 до 60 секунд.")
        return

    if not parts[2].isdigit():
        await message.answer("Количество должно быть числом.")
        return

    delay = max(_MIN_DELAY, min(delay, _MAX_DELAY))
    requested = int(parts[2])
    text = parts[3]
    if requested <= 0:
        return

    count = clamp(requested, _MAX_COUNT)
    if count < requested:
        await _notify_owner(bot, owner_id, _clamp_notice(requested, count))

    await _send_sequence(bot, owner_id, message.chat.id, [text] * count, delay)


@router.message(F.text.regexp(r"^\.wspam(\s|$)"))
async def cmd_wspam(message: Message, bot: Bot, owner_id: int):
    if message.from_user.id != owner_id:
        return

    text = message.text[len(".wspam") :].strip()
    if not text:
        await message.answer("Формат: .wspam [предложение]")
        return

    all_words = text.split()
    words = all_words[:_MAX_COUNT]
    if len(all_words) > _MAX_COUNT:
        await _notify_owner(bot, owner_id, _clamp_notice(len(all_words), len(words)))

    await _send_sequence(bot, owner_id, message.chat.id, words, _DEFAULT_STEP_DELAY)


@router.message(F.text.regexp(r"^\.lspam(\s|$)"))
async def cmd_lspam(message: Message, bot: Bot, owner_id: int):
    if message.from_user.id != owner_id:
        return

    text = message.text[len(".lspam") :].strip()
    if not text:
        await message.answer("Формат: .lspam [слово или предложение]")
        return

    all_chars = [char for char in text if not char.isspace()]
    chars = all_chars[:_MAX_COUNT]
    if len(all_chars) > _MAX_COUNT:
        await _notify_owner(bot, owner_id, _clamp_notice(len(all_chars), len(chars)))

    await _send_sequence(bot, owner_id, message.chat.id, chars, _DEFAULT_STEP_DELAY)
