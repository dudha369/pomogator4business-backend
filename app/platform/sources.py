"""Источники событий: бизнес-бот и юзербот.

Юзербот пишет в `message_history` под синтетическим `connection_id = "ub:<owner_id>"`:
строки `Connection` у него нет (её видят автоответчик, часы и статистика), а владелец
определяется по самому префиксу. Отдельной колонки `source` не нужно."""

USERBOT_PREFIX = "ub:"
# peer id каналов и супергрупп (get_peer_id) начинается с -100…; у обычных чатов — выше
CHANNEL_PEER_LIMIT = -1_000_000_000_000


def userbot_connection_id(owner_id: int) -> str:
    return f"{USERBOT_PREFIX}{owner_id}"


def userbot_owner(connection_id) -> int | None:
    """Владелец по `ub:<id>`; None — это не подключение юзербота."""
    if isinstance(connection_id, str) and connection_id.startswith(USERBOT_PREFIX):
        tail = connection_id[len(USERBOT_PREFIX) :]
        return int(tail) if tail.isdigit() else None
    return None


def source_of(connection_id) -> str:
    return "userbot" if userbot_owner(connection_id) is not None else "bot"


def is_channel_peer(chat_id: int) -> bool:
    return chat_id <= CHANNEL_PEER_LIMIT
