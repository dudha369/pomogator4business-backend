"""Сводка для главной страницы мини-приложения одним запросом.

Раньше фронтенд собирал её из шести запросов (`/account`, `/mirror`, `/settings`,
`/commands`, `/stats`, `/archive`). Здесь те же данные, но без подключения
владельца ответ не падает в 404: главная показывает «бот не подключён».
"""

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.features.alerts import service as alerts_service
from app.features.archive.api import ArchiveEntry
from app.features.archive.media import attach_media_info
from app.features.archive.queries import get_archive_page
from app.features.emoji_clock.queries import (
    is_emoji_status_enabled,
    is_emoji_status_granted,
)
from app.features.mirror.queries import get_mirror
from app.features.stats.api import StatsOut, get_stats
from app.platform.api.deps import Owner, require_user
from app.platform.telegram.registry import registry
from db.models.connection import get_connection_by_owner
from db.models.module_settings import list_disabled_modules

router = APIRouter()
log = logging.getLogger(__name__)

RECENT_ARCHIVE_LIMIT = 3


class HomeOut(BaseModel):
    connected: bool
    owner_name: str | None
    owner_username: str | None
    mirror_connected: bool
    commands_total: int
    modules_enabled: int
    modules_total: int
    emoji_status_granted: bool
    emoji_status_enabled: bool  # включён И разрешён — как показывает главная
    alerts_active: int  # число видимых предупреждений («Проблемы и настройки»)
    stats: StatsOut | None  # необязательная часть: при сбое None
    recent_archive: list[ArchiveEntry]  # необязательная часть: при сбое []


async def _recent_archive(connection_id: str) -> list[dict]:
    entries, _ = await get_archive_page(connection_id, None, RECENT_ARCHIVE_LIMIT)
    await attach_media_info(connection_id, entries)
    return entries


@router.get("/home", response_model=HomeOut)
async def get_home(user: dict = Depends(require_user)):
    owner_id = user["id"]
    connection = await get_connection_by_owner(owner_id)
    mirror = await get_mirror(owner_id)
    granted = await is_emoji_status_granted(owner_id)
    enabled = await is_emoji_status_enabled(owner_id)

    modules = registry.modules()
    disabled: set = set()
    stats = None
    recent: list[dict] = []
    if connection:
        connection_id = connection["connection_id"]
        disabled = set(await list_disabled_modules(connection_id))
        try:
            stats = await get_stats(Owner(user=user, connection=connection))
            recent = await _recent_archive(connection_id)
        except Exception:  # счётчики и лента не должны ронять главную
            log.exception("Главная: не удалось собрать счётчики или архив")

    try:
        alerts_active = len(await alerts_service.list_active(owner_id))
    except Exception:  # счётчик не должен ронять главную
        log.exception("Главная: не удалось посчитать предупреждения")
        alerts_active = 0

    return {
        "alerts_active": alerts_active,
        "connected": connection is not None,
        "owner_name": connection.get("owner_name") if connection else None,
        "owner_username": connection.get("owner_username") if connection else None,
        "mirror_connected": bool(mirror and mirror["is_active"]),
        "commands_total": sum(len(commands) for commands in modules.values()),
        "modules_enabled": sum(1 for name in modules if name not in disabled),
        "modules_total": len(modules),
        "emoji_status_granted": granted,
        "emoji_status_enabled": granted and enabled,
        "stats": stats,
        "recent_archive": recent,
    }
