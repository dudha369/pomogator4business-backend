"""Чьи записи видит мини-приложение: все подключения владельца.

Раньше архив открывался только при бизнес-подключении (`current_owner`). У владельца,
который подключил лишь юзербота, его не было бы вовсе, поэтому архив работает от
пользователя: бизнес-подключение (если есть) плюс подключение юзербота."""

from dataclasses import dataclass

from fastapi import Depends

from app.platform.api.deps import require_user
from app.platform.sources import userbot_connection_id
from db.models.connection import get_connection_by_owner


@dataclass
class ArchiveScope:
    user: dict
    connection_ids: list[str]  # бизнес-подключение (если есть) и `ub:<owner>`
    settings_connection_id: str  # где хранятся настройки архива
    owner_chat_id: int  # куда бот присылает файлы (личка владельца)

    @property
    def id(self) -> int:
        return self.user["id"]


async def archive_scope(user: dict = Depends(require_user)) -> ArchiveScope:
    business = await get_connection_by_owner(user["id"])
    userbot = userbot_connection_id(user["id"])
    return ArchiveScope(
        user=user,
        connection_ids=([business["connection_id"]] if business else []) + [userbot],
        settings_connection_id=business["connection_id"] if business else userbot,
        owner_chat_id=business["owner_chat_id"] if business else user["id"],
    )
