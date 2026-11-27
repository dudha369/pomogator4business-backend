"""Pydantic-модели ответов REST, которыми пользуются сразу несколько эндпоинтов.

Модели одного эндпоинта лежат рядом с ним. Здесь — только общие формы данных
(настройки, которые отдают и `/account`, и `/backup/export`, и т.п.). Поля и
`null`-ы повторяют прежний JSON байт в байт: фронтенд ничего не должен заметить.
"""

from typing import Literal

from pydantic import BaseModel


class MirrorStatus(BaseModel):
    connected: bool
    username: str | None


class EmojiStyle(BaseModel):
    id: str
    titles: dict[str, str]
    available: bool  # False — паки стиля ещё не загружены
    preview_emoji_id: str | None  # эмодзи текущей минуты для превью (None — нет)


class EmojiStatusState(BaseModel):
    granted: bool
    enabled: bool
    style: str
    styles: list[EmojiStyle]


class RemindersSettings(BaseModel):
    enabled: bool
    hours: int
    quiet_start_minutes: int | None
    quiet_end_minutes: int | None
    favorites_only: bool


class AiCore(BaseModel):
    enabled: bool
    mode: Literal["draft", "auto"]
    instructions: str | None
    history_messages: int
    daily_limit: int


class KeywordReply(BaseModel):
    id: int
    keyword: str
    reply_text: str


class CommandAlias(BaseModel):
    alias: str
    command: str


class Template(BaseModel):
    name: str
    text: str


class ChatFlagValues(BaseModel):
    no_autoreply: bool
    no_ai: bool
    no_remind: bool


class ChatFlags(ChatFlagValues):
    chat_id: int
