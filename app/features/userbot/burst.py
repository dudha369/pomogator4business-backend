"""Массовое удаление: уведомления одного чата копятся короткое окно.

Админ-зачистка в большой группе — сотни удалений за секунды. Каждое из них уже
записано в архив (запись идёт сразу, до этого модуля), а уведомления копятся
`USERBOT_BURST_WINDOW` секунд: мало сообщений — приходят как обычно, много — вместо них
ОДНА сводка с точным числом и кнопкой в архив. Без aiogram."""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from app.platform.tasks import spawn
from config import settings


@dataclass
class Batch:
    units: list = field(default_factory=list)  # группы сообщений (альбом = одна группа)
    count: int = 0  # число сообщений (не групп)
    started: int = 0
    last: int = 0


Flush = Callable[[int, int, Batch], Awaitable[None]]

_batches: dict[tuple[int, int], Batch] = {}
_tasks: set[asyncio.Task] = set()


async def submit(owner_id: int, chat_id: int, units: list, flush: Flush) -> None:
    """Добавляет удалённое в пачку чата; первая порция запускает окно ожидания."""
    key = (owner_id, chat_id)
    now = int(time.time())
    batch = _batches.get(key)
    is_new = batch is None
    if batch is None:
        batch = _batches[key] = Batch(started=now)
    batch.units.extend(units)
    batch.count += sum(len(unit) for unit in units)
    batch.last = now
    if is_new:
        task = spawn(_after_window(key, flush), name=f"userbot-burst-{chat_id}")
        _tasks.add(task)
        task.add_done_callback(_tasks.discard)


async def _after_window(key: tuple[int, int], flush: Flush) -> None:
    await asyncio.sleep(settings.USERBOT_BURST_WINDOW)
    batch = _batches.pop(key, None)  # новые удаления после этого — уже новая пачка
    if batch is not None:
        await flush(key[0], key[1], batch)


async def drain() -> None:
    """Дождаться всех открытых окон (для тестов и остановки)."""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
