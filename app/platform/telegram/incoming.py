"""Контекст бизнес-сообщения для middleware и обработчиков.

`load_incoming` — outer middleware: находит подключение, считает владельца и выключенные
модули, кладёт `Incoming` в `data["inc"]`. Нет подключения или оно выключено — цепочка
останавливается. Дальше шаги (inner middleware) читают `inc`, а не лезут в БД сами."""

from dataclasses import dataclass, field

from aiogram import Bot
from aiogram.types import Message

from db.models.connection import get_connection
from app.features.history.service import log_message
from db.models.module_settings import list_disabled_modules


@dataclass
class Incoming:
    bot: Bot
    message: Message
    connection: dict
    disabled: set = field(default_factory=set)
    is_owner: bool = False

    @property
    def connection_id(self) -> str:
        return self.connection["connection_id"]

    @property
    def chat_id(self) -> int:
        return self.message.chat.id

    @property
    def text(self):
        return self.message.text or self.message.caption

    def enabled(self, module: str) -> bool:
        return module not in self.disabled


async def load_incoming(handler, message: Message, data: dict):
    connection = await get_connection(message.business_connection_id)
    if not connection or not connection["is_enabled"]:
        return None
    data["inc"] = Incoming(
        bot=data["bot"],
        message=message,
        connection=connection,
        disabled=await list_disabled_modules(connection["connection_id"]),
        is_owner=message.from_user.id == connection["owner_id"],
    )
    return await handler(message, data)


async def owner_journal(handler, message: Message, data: dict):
    """Журнал нужен только для .del/.panic — они трогают сообщения владельца."""
    inc: Incoming = data["inc"]
    if inc.is_owner:
        await log_message(inc.connection_id, inc.chat_id, message.message_id)
    return await handler(message, data)
