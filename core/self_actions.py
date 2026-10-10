import time
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
) -> None:
    """Единая точка удаления сообщений ботом через Business API.

    Помечает message_id как "самоудаление" до вызова API, чтобы archive.py
    не отреагировал на прилетевший следом deleted_business_messages.
    """
    message_ids = list(message_ids)
    if not message_ids:
        return

    for message_id in message_ids:
        _mark(connection_id, chat_id, message_id)

    try:
        await bot.delete_business_messages(
            business_connection_id=connection_id,
            message_ids=message_ids,
        )
    except Exception:
        log_suppressed("core/self_actions.py:48", benign=True)
