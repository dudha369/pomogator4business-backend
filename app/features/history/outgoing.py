"""Сообщения, отправленные самим ботом в бизнес-чат, — в историю.

Telegram не присылает боту апдейты о его собственных сообщениях, поэтому шаг
`record_history` их не видит, и при удалении архиву нечего показать. Запись делаем на
уровне сессии Bot (как `BotEditMarker` для правок): так не нужно помнить об обёртке в
каждом месте отправки (`.timer`, `.bomb`, игры, ответы команд…)."""

import time

from aiogram.client.session.middlewares.base import BaseRequestMiddleware

from app.features.history import rules
from app.features.history.adapter import build_snapshot
from app.features.history.service import save_history
from app.features.vault.service import owner_of
from app.platform.utils import log_suppressed


def _messages(result):
    """Результат Send*: одно сообщение или список (sendMediaGroup)."""
    items = result if isinstance(result, list) else [result]
    # у ответов-«True» (sendChatAction и т. п.) message_id нет
    return [m for m in items if hasattr(m, "message_id")]


async def record_outgoing(bot, connection_id: str, message) -> None:
    """Снимок отправленного ботом сообщения: владелец — автор (is_owner=True).

    save_history идемпотентен по (подключение, чат, id): если Telegram всё же пришлёт
    апдейт об этом сообщении, запись просто обновится, а не задвоится."""
    snapshot = build_snapshot(message, bot_id=getattr(bot, "id", None))
    if snapshot is None:
        return
    owner = await owner_of(connection_id)
    if owner is not None and not await rules.should_archive(
        owner, message.chat.id, "private", "bot"
    ):
        return  # чат выключен в правилах архива
    await save_history(
        connection_id,
        message.chat.id,
        message.message_id,
        True,
        snapshot["text"],
        int(message.date.timestamp()) if message.date else int(time.time()),
        snapshot=snapshot,
    )


class OutgoingRecorder(BaseRequestMiddleware):
    """Пишет в историю всё, что бот отправил от имени владельца (Business API).

    Правки (Edit*) не трогаем — их не должно быть в архиве; сбой записи никогда не
    ломает саму отправку."""

    async def __call__(self, make_request, bot, method):
        result = await make_request(bot, method)
        connection_id = getattr(method, "business_connection_id", None)
        if connection_id and type(method).__name__.startswith("Send"):
            for message in _messages(result):
                try:
                    await record_outgoing(bot, connection_id, message)
                except Exception:
                    log_suppressed("app/features/history/outgoing.py:record")
        return result


def install_outgoing_recorder(bot) -> None:
    """Подключить запись к основному боту (зеркальные боты бизнес-апдейтов не ведут)."""
    bot.session.middleware(OutgoingRecorder())
