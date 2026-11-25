"""Запросы к правилам архива по чатам."""

import time

from app.features.history.models import ChatArchiveRule
from app.platform.ttl_cache import ttl_cache

GROUP_KINDS = ("group", "supergroup", "channel")


@ttl_cache
async def get_rule(owner_id: int, chat_id: int) -> dict | None:
    """Правило чата (кэш 5 с: читается на каждое сообщение). None — строки нет."""
    rows = await ChatArchiveRule.filter(owner_id=owner_id, chat_id=chat_id).values(
        "kind", "enabled", "media_enabled", "notify"
    )
    return rows[0] if rows else None


async def list_rules(owner_id: int) -> list[dict]:
    return (
        await ChatArchiveRule.filter(owner_id=owner_id)
        .order_by("id")
        .values("chat_id", "kind", "enabled", "media_enabled", "notify")
    )


async def count_enabled_groups(owner_id: int) -> int:
    """Сколько групп и каналов включено в архив (для лимита `archive_groups`)."""
    return await ChatArchiveRule.filter(
        owner_id=owner_id, kind__in=GROUP_KINDS, enabled=True
    ).count()


async def upsert_rule(
    owner_id: int, chat_id: int, kind: str, values: dict, defaults: dict
) -> None:
    """Создаёт правило (поля, которых нет в `values`, — из `defaults`) или меняет
    только переданные поля существующего."""
    now = int(time.time())
    row = await ChatArchiveRule.get_or_none(owner_id=owner_id, chat_id=chat_id)
    if row is None:
        await ChatArchiveRule.create(
            owner_id=owner_id,
            chat_id=chat_id,
            kind=kind,
            created_at=now,
            updated_at=now,
            **{**defaults, **values},
        )
        return
    await ChatArchiveRule.filter(id=row.id).update(updated_at=now, **values)
