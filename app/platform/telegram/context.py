import json
import logging
from dataclasses import dataclass

from aiogram import Bot
from aiogram.types import Message, ReplyParameters

from app.features.alerts.bot import report
from app.platform.tasks import spawn
from db.models.message_log import log_message
from app.platform.i18n import t
from core.self_actions import delete_own_messages
from core.utils import log_suppressed

logger = logging.getLogger("bot.context")


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
        await log_message(self.connection_id, self.chat_id, msg.message_id)
        return msg

    async def delete_command_message(self):
        if self.dm:
            return
        await delete_own_messages(
            self.bot, self.connection_id, self.chat_id, [self.message.message_id]
        )

    async def edit_command_message(self, text: str, **kwargs) -> bool:
        """Заменить сообщение-команду результатом. True — получилось (в личке с ботом
        править нечего: просто отвечаем)."""
        if self.dm:
            await self.reply(text, **kwargs)
            return True
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
            return False
        return True

    @property
    def is_owner_author(self) -> bool:
        user = self.message.from_user
        return user is not None and user.id == self.connection["owner_id"]

    def _can_delete_others(self) -> bool:
        try:
            rights = json.loads(self.connection.get("rights_json") or "{}")
        except (json.JSONDecodeError, TypeError):
            return False
        return bool(rights.get("can_delete_all_messages"))

    async def present(self, text: str, **kwargs) -> int:
        """Показать результат команды и вернуть message_id итогового сообщения.

        Владелец: его сообщение-команда превращается в результат. Собеседник (игры
        с owner_only=False): правка чужого сообщения невозможна, поэтому, если у бота
        есть право удалять чужие сообщения, команда удаляется, а игра приходит новым
        сообщением; нет права или удалить не вышло — игра идёт ответом на команду."""
        if self.dm:
            return (await self.reply(text, **kwargs)).message_id

        if self.is_owner_author:
            if await self.edit_command_message(text, **kwargs):
                return self.message.message_id
            return (await self.reply(text, **kwargs)).message_id

        deleted = False
        if self._can_delete_others():
            deleted = await delete_own_messages(
                self.bot, self.connection_id, self.chat_id, [self.message.message_id]
            )
        else:
            name = self.message.from_user.full_name if self.message.from_user else "?"
            spawn(report(self.connection["owner_id"], "no_delete_right", name=name))
            logger.info(
                "Нет права can_delete_all_messages (connection=%s): игра ответом на команду",
                self.connection_id,
            )
        if not deleted:
            kwargs["reply_parameters"] = ReplyParameters(
                message_id=self.message.message_id
            )
        return (await self.reply(text, **kwargs)).message_id

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
