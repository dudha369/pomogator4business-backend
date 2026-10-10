from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import Message

from core import database as db
from core.i18n import t
from core.self_actions import delete_own_messages
from core.utils import log_suppressed


@dataclass
class CommandContext:
    bot: Bot
    message: Message
    connection: dict
    args: str
    locale: str = "ru"
    # True — команда вызвана в личке с ботом, а не в бизнес-чате: ответы идут
    # обычными сообщениями (без business_connection_id), сообщение-команду
    # нельзя ни отредактировать, ни удалить
    dm: bool = False

    @property
    def connection_id(self):
        return self.connection["connection_id"]

    @property
    def chat_id(self):
        return self.message.chat.id

    def t(self, key, **kwargs):
        return t(key, self.locale, **kwargs)

    async def reply(self, text: str, **kwargs):
        if self.dm:
            return await self.bot.send_message(
                chat_id=self.chat_id, text=text, **kwargs
            )
        msg = await self.bot.send_message(
            business_connection_id=self.connection_id,
            chat_id=self.chat_id,
            text=text,
            **kwargs,
        )
        await db.log_message(self.connection_id, self.chat_id, msg.message_id)
        return msg

    async def delete_command_message(self):
        if self.dm:
            return
        await delete_own_messages(
            self.bot, self.connection_id, self.chat_id, [self.message.message_id]
        )

    async def edit_command_message(self, text: str, **kwargs):
        if self.dm:
            await self.reply(text, **kwargs)
            return
        try:
            await self.bot.edit_message_text(
                business_connection_id=self.connection_id,
                chat_id=self.chat_id,
                message_id=self.message.message_id,
                text=text,
                **kwargs,
            )
        except Exception:
            log_suppressed("core/context.py:54", benign=True)

    async def usage_error(self, text: str, **kwargs):
        await self.delete_command_message()
        try:
            await self.bot.send_message(
                chat_id=self.chat_id if self.dm else self.connection["owner_chat_id"],
                text=text,
                **kwargs,
            )
        except Exception:
            log_suppressed("core/context.py:65", benign=True)
