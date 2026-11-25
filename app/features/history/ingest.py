"""Единая точка записи сообщения в историю: бизнес-бот и юзербот приходят сюда.

Дальше всё общее (`save_history`, шифрование vault, архив). Без aiogram и Telethon:
источник присылает готовый словарь-снимок. Здесь решается, писать ли сообщение вообще:
правила чатов (`history.rules`) и приоритет бизнес-бота."""

from app.features.history import rules
from app.features.history.service import save_history
from app.features.vault.service import owner_of
from app.platform.sources import userbot_owner
from db.models.connection import get_connection_by_owner


async def _business_covers(owner_id: int) -> bool:
    connection = await get_connection_by_owner(owner_id)
    return bool(connection and connection["is_enabled"])


async def ingest(
    *,
    source: str,  # "bot" | "userbot"
    connection_id: str,
    chat_id: int,
    message_id: int,
    is_owner: bool,
    text: str | None,
    ts: int,
    snapshot: dict | None,
    media: dict | None = None,
    chat_kind: str | None = None,
) -> bool:
    """True — записано.

    1. Личные чаты юзербот не пишет, пока их ведёт бизнес-бот: у бизнес-бота приоритет
       (иначе одно сообщение лежало бы в двух версиях).
    2. Выключенный правилами чат не пишется вообще (и уведомлений по нему не будет).
    `chat_kind` — private | group | supergroup | channel; без него по знаку chat_id."""
    kind = chat_kind or rules.kind_of_chat(chat_id)
    if source == "userbot" and kind == "private":
        owner = userbot_owner(connection_id)
        if owner is not None and await _business_covers(owner):
            return False
    owner = await owner_of(connection_id)
    if owner is not None and not await rules.should_archive(
        owner, chat_id, kind, source
    ):
        return False
    await save_history(
        connection_id,
        chat_id,
        message_id,
        is_owner,
        text,
        ts,
        snapshot=snapshot,
        **(media or {}),
    )
    return True
