"""Периодическая очистка разрастающихся таблиц.

Платформа только запускает цикл. Что и когда чистить, решает сама фича: в
`app/features/<f>/retention.py` функция регистрируется декоратором
`@retention_task("имя")` и получает текущее время (unix-секунды). Вернула число
удалённых/обнулённых строк — оно попадёт в лог; вернула None — очистка
выключена настройкой. Сбой одной задачи не мешает остальным.

Сроки настраиваются переменными окружения (см. config.py)."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from app.features import FEATURES, feature_module

logger = logging.getLogger("bot.retention")

DAY = 86400
_INTERVAL_SECONDS = 6 * 3600
_FIRST_RUN_DELAY_SECONDS = 300

RetentionTask = Callable[[int], Awaitable[int | None]]
_TASKS: dict[str, RetentionTask] = {}


def retention_task(name: str) -> Callable[[RetentionTask], RetentionTask]:
    """Регистрирует задачу очистки под именем `name` (оно же ключ в логе)."""

    def register(task: RetentionTask) -> RetentionTask:
        if name in _TASKS:
            raise ValueError(f"Задача очистки {name!r} уже зарегистрирована")
        _TASKS[name] = task
        return task

    return register


def registered_tasks() -> dict[str, RetentionTask]:
    """Все задачи, включая объявленные в `retention.py` фич."""
    for feature in FEATURES:
        feature_module(feature, "retention")
    return dict(_TASKS)


async def run_retention_once(now=None):
    now = int(now if now is not None else time.time())
    stats = {}
    for name, task in registered_tasks().items():
        try:
            removed = await task(now)
        except Exception:
            logger.exception("Сбой задачи очистки %s", name)
            continue
        if removed is not None:
            stats[name] = removed
    return stats


async def run_retention_loop():
    await asyncio.sleep(_FIRST_RUN_DELAY_SECONDS)
    while True:
        try:
            stats = await run_retention_once()
            logger.info("Очистка выполнена: %s", stats)
        except Exception:
            logger.exception("Сбой очистки старых данных")
        await asyncio.sleep(_INTERVAL_SECONDS)
