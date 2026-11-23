"""Единая точка записи сообщения в историю: бизнес-бот и юзербот приходят сюда.

Дальше всё общее (`save_history`, шифрование vault, архив). Без aiogram и Telethon:
источник присылает готовый словарь-снимок."""

from app.features.history.service import save_history
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
) -> bool:
    """True — записано. Личные чаты юзербот не пишет, пока их ведёт бизнес-бот:
    у бизнес-бота приоритет (иначе одно сообщение лежало бы в двух версиях)."""
    if source == "userbot" and chat_id > 0:
        owner = userbot_owner(connection_id)
        if owner is not None and await _business_covers(owner):
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
