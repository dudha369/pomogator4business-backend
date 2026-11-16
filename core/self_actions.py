import time

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.methods import (
    EditMessageCaption,
    EditMessageMedia,
    EditMessageReplyMarkup,
    EditMessageText,
)

from core.utils import log_suppressed

_TTL_SECONDS = 30
_pending: dict[tuple[str, int, int], float] = {}


def _sweep() -> None:
    now = time.monotonic()
    expired = [key for key, ts in _pending.items() if now - ts > _TTL_SECONDS]
    for key in expired:
        _pending.pop(key, None)


def _mark(connection_id: str, chat_id: int, message_id: int) -> None:
    _sweep()
    _pending[(connection_id, chat_id, message_id)] = time.monotonic()


def consume_self_delete(connection_id: str, chat_id: int, message_id: int) -> bool:
    """Возвращает True и забывает запись, если это удаление инициировал бот."""
    key = (connection_id, chat_id, message_id)
    if key in _pending:
        del _pending[key]
        return True
    return False


async def delete_own_messages(
    bot, connection_id: str, chat_id: int, message_ids
) -> bool:
    """Единая точка удаления сообщений ботом через Business API.

    Помечает message_id как "самоудаление" до вызова API, чтобы архив (app/features/archive/bot/deleted.py)
    не отреагировал на прилетевший следом deleted_business_messages.
    Возвращает True, если Telegram принял удаление (вызывающий решает, что
    делать с данными при неудаче — например, не стирать журнал).
    """
    message_ids = list(message_ids)
    if not message_ids:
        return True

    for message_id in message_ids:
        _mark(connection_id, chat_id, message_id)

    try:
        await bot.delete_business_messages(
            business_connection_id=connection_id,
            message_ids=message_ids,
        )
    except Exception:
        log_suppressed("core/self_actions.py:48", benign=True)
        # удаления не было — метка не нужна, иначе настоящее удаление
        # этого сообщения в ближайшие 30 с не попадёт в архив
        for message_id in message_ids:
            _pending.pop((connection_id, chat_id, message_id), None)
        return False
    return True


# --- правки, сделанные самим ботом -------------------------------------------------
# Telegram присылает edited_business_message и на правки бота (typewriter, ходы в играх,
# «Было/Стало»): в архив они попадать не должны. Метка живёт, пока бот правит сообщение
# (каждая правка её продлевает), и не «съедается» при проверке: на одну правку может
# прийти несколько апдейтов.
_EDIT_TTL_SECONDS = 20
_bot_edits: dict[tuple[str, int, int], float] = {}

_EDIT_METHODS = (
    EditMessageText,
    EditMessageCaption,
    EditMessageMedia,
    EditMessageReplyMarkup,
)


def _mark_bot_edit(connection_id: str, chat_id: int, message_id: int) -> None:
    now = time.monotonic()
    for key in [k for k, until in _bot_edits.items() if until < now]:
        del _bot_edits[key]
    _bot_edits[(connection_id, chat_id, message_id)] = now + _EDIT_TTL_SECONDS


def is_bot_edit(connection_id: str, chat_id: int, message_id: int) -> bool:
    until = _bot_edits.get((connection_id, chat_id, message_id))
    return until is not None and until >= time.monotonic()


class BotEditMarker(BaseRequestMiddleware):
    """Единая точка для ВСЕХ правок бота в бизнес-чатах: метка ставится на уровне
    сессии Bot, поэтому не нужно помнить об обёртке в каждом месте вызова
    (message.edit_text, bot.edit_message_text, edit_reply_markup…)."""

    async def __call__(self, make_request, bot, method):
        if isinstance(method, _EDIT_METHODS):
            connection_id = getattr(method, "business_connection_id", None)
            chat_id = getattr(method, "chat_id", None)
            message_id = getattr(method, "message_id", None)
            if connection_id and chat_id is not None and message_id is not None:
                _mark_bot_edit(connection_id, int(chat_id), message_id)
        return await make_request(bot, method)


def install_edit_marker(bot) -> None:
    """Подключить маркер к боту (основному и каждому зеркальному)."""
    bot.session.middleware(BotEditMarker())
