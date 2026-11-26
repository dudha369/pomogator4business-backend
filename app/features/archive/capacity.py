"""Помещается ли новое событие в лимиты архива по тарифу (17.3). Без aiogram.

Лимит мягкий: когда места нет, событие не пишется в веб-архив, но уведомление владельцу
приходит как обычно, а то, что уже сохранено, не удаляется. Гонка двух записей может
превысить лимит на единицы — для мягкого лимита это допустимо."""

import logging
import time
from dataclasses import dataclass, field

from app.features.archive.queries import archive_usage
from app.features.limits.plans import limit_for
from app.features.limits.service import Denied, check, plan_of
from app.features.vault import service as vault
from app.platform.sources import userbot_connection_id
from db.models.connection import get_connection_by_owner

logger = logging.getLogger("archive.capacity")

REPORT_EVERY = 3600  # одно предупреждение в час на процесс; дальше — пауза в alerts
_reported: dict[tuple[int, str], float] = {}


@dataclass
class Admission:
    write: bool = True  # писать ли событие в архив
    keep_media: bool = True  # хранить ли байты файла внутри записи
    denied: list[Denied] = field(default_factory=list)


async def owner_connection_ids(owner_id: int) -> list[str]:
    """Подключения владельца в архиве: бизнес (если есть) и юзербот."""
    business = await get_connection_by_owner(owner_id)
    ids = [business["connection_id"]] if business else []
    return [*ids, userbot_connection_id(owner_id)]


async def usage(owner_id: int) -> tuple[int, int]:
    """(записей, байт файлов) владельца."""
    return await archive_usage(await owner_connection_ids(owner_id))


async def admit(connection_id: str, media_bytes: int = 0) -> Admission:
    """Решение для одного события. Сбой проверки не должен терять данные: при ошибке
    пишем как обычно, а ошибка уходит в журнал наблюдаемости."""
    try:
        owner_id = await vault.owner_of(connection_id)
        if owner_id is None:
            return Admission()
        plan = (await plan_of(owner_id))["plan"]
        if (
            limit_for(plan, "archive_entries") is None
            and limit_for(plan, "archive_media_bytes") is None
        ):
            return Admission()  # безлимит: запросов к архиву не делаем
        entries, size = await usage(owner_id)
        result = Admission()
        room = await check(owner_id, "archive_entries", 1, current=entries)
        if isinstance(room, Denied):
            result.write = result.keep_media = False
            result.denied.append(room)
        if media_bytes:
            space = await check(owner_id, "archive_media_bytes", media_bytes, size)
            if isinstance(space, Denied):
                result.keep_media = False
                if result.write:  # записи не будет — про файлы отдельно не сообщаем
                    result.denied.append(space)
        return result
    except Exception:
        logger.exception("Проверка лимита архива не удалась: событие записано")
        return Admission()


async def report_full(connection_id: str, admission: Admission) -> None:
    """Предупредить владельца (alert `limit_reached:<metric>`). Не чаще раза в час на
    процесс: при массовом удалении не дёргаем БД на каждое сообщение."""
    if not admission.denied:
        return
    from app.features.limits.bot import report_denied  # лениво: тянет aiogram

    owner_id = await vault.owner_of(connection_id)
    now = time.monotonic()
    for denied in admission.denied:
        key = (owner_id, denied.metric)
        if owner_id is None or now - _reported.get(key, -REPORT_EVERY) < REPORT_EVERY:
            continue
        _reported[key] = now
        await report_denied(owner_id, denied)
