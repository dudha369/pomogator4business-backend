"""Что писать в архив: правила по чатам, общие для бизнес-бота и юзербота.

Умолчания зависят от вида чата и источника: личные чаты бизнес-бота включены,
всё остальное (личные чаты юзербота, группы, каналы) выключено, пока владелец не
включит чат сам. Строка в `chat_archive_rules` переопределяет умолчание. Без aiogram."""

from dataclasses import dataclass

from app.features.history import rule_queries
from app.platform.sources import is_channel_peer
from app.platform.ttl_cache import clear_all


@dataclass(frozen=True)
class Rule:
    enabled: bool
    media: bool  # сохранять файлы байтами (только юзербот)
    notify: bool  # присылать уведомления об удалении и правке


def kind_of_chat(chat_id: int) -> str:
    """Вид чата по peer id, если тип неизвестен (для строк без правила)."""
    if chat_id > 0:
        return "private"
    return "supergroup" if is_channel_peer(chat_id) else "group"


def default_rule(kind: str, source: str) -> Rule:
    return Rule(enabled=kind == "private" and source == "bot", media=False, notify=True)


async def rule_for(owner_id: int, chat_id: int, kind: str, source: str) -> Rule:
    row = await rule_queries.get_rule(owner_id, chat_id)
    if row is None:
        return default_rule(kind, source)
    return Rule(row["enabled"], row["media_enabled"], row["notify"])


async def should_archive(owner_id: int, chat_id: int, kind: str, source: str) -> bool:
    return (await rule_for(owner_id, chat_id, kind, source)).enabled


async def set_rule(owner_id: int, chat_id: int, kind: str, **changes) -> None:
    """Меняет правило (`enabled`, `media_enabled`, `notify`); None-поля не трогает."""
    values = {k: v for k, v in changes.items() if v is not None}
    base = default_rule(kind, "bot")  # новая строка не должна менять остальные поля
    defaults = {
        "enabled": base.enabled,
        "media_enabled": base.media,
        "notify": base.notify,
    }
    await rule_queries.upsert_rule(owner_id, chat_id, kind, values, defaults)
    clear_all()
