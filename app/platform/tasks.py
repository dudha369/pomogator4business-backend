"""spawn() — фоновая задача с сильной ссылкой и логированием падений.

asyncio.create_task без ссылки: event loop держит задачу слабо, и сборщик мусора
может уничтожить её на полпути; исключение при этом пропадает молча."""

import asyncio
import logging

logger = logging.getLogger(__name__)

_tasks: set[asyncio.Task] = set()


def spawn(coro, *, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _tasks.add(task)
    task.add_done_callback(_on_done)
    return task


def _on_done(task: asyncio.Task) -> None:
    _tasks.discard(task)
    if not task.cancelled() and task.exception():
        logger.error(
            "Фоновая задача %s упала", task.get_name(), exc_info=task.exception()
        )
