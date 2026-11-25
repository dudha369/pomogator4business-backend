"""Простые типы, которыми адаптер Telethon и логика событий обмениваются друг с другом.

Ни Telethon, ни aiogram здесь нет: логика (`events.py`) не знает библиотеку."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field


@dataclass
class UbChat:
    id: int  # peer id в формате Bot API (-100… у каналов и супергрупп)
    kind: str  # private | group | supergroup | channel
    title: str | None = None
    username: str | None = None


@dataclass
class UbMessage:
    chat: UbChat
    message_id: int
    ts: int
    is_out: bool
    snapshot: dict  # формат history.snapshot; raw_json заполняет events
    sender_id: int | None = None
    sender_name: str | None = None
    sender_username: str | None = None
    # скачать байты файла (только вызывается, если чату разрешены файлы)
    download: Callable[[], Awaitable[bytes | None]] | None = field(
        default=None, repr=False
    )


@dataclass
class UbDialog:
    id: int
    kind: str  # private | group | supergroup | channel
    title: str
    username: str | None = None
    members: int | None = None
    archived: bool = False
    is_bot: bool = False
