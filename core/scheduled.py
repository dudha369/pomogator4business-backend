"""Отложенные действия (.timer, .bomb): хранятся в БД, исполняются одним циклом.

Раньше каждое действие жило в `asyncio.sleep` до 24 ч и пропадало при рестарте
или засыпании Render. Теперь источник истины — таблица `scheduled_tasks`; цикл
спит до ближайшего `run_at` (без опроса) и просыпается раньше, если добавили
более раннюю задачу. Просроченное за время простоя выполняется при старте."""

import asyncio
import logging
import time
from contextlib import suppress

from db.models.scheduled_task import (
    add_scheduled_task,
    claim_scheduled_task,
    list_due_scheduled_tasks,
    next_scheduled_run_at,
)
from core.self_actions import delete_own_messages

logger = logging.getLogger("bot.scheduled")

_MAX_SLEEP = 60  # страховка: не спим дольше, даже если задач нет
_MIN_SLEEP = 0.2
_wake: asyncio.Event | None = None  # создаётся внутри цикла (привязка к его loop)


async def schedule(
    kind, connection_id, chat_id, delay_seconds, *, message_id=None, text=None
):
    await add_scheduled_task(
        kind,
        connection_id,
        chat_id,
        int(time.time() + delay_seconds),
        message_id=message_id,
        text=text,
    )
    if _wake is not None:
        _wake.set()


async def _run_timer(bot, task):
    await bot.send_message(
        business_connection_id=task["connection_id"],
        chat_id=task["chat_id"],
        text=task["text"],
        parse_mode=None,
    )


async def _run_bomb(bot, task):
    await delete_own_messages(
        bot, task["connection_id"], task["chat_id"], [task["message_id"]]
    )


_EXECUTORS = {"timer": _run_timer, "bomb": _run_bomb}


async def process_due(bot, now=None) -> int:
    """Выполняет всё, что пора. Возвращает число выполненных задач."""
    now = int(now if now is not None else time.time())
    done = 0
    for task in await list_due_scheduled_tasks(now):
        # at-most-once: забираем до выполнения (на деплое живут два процесса)
        if not await claim_scheduled_task(task["id"]):
            continue
        executor = _EXECUTORS.get(task["kind"])
        if executor is None:
            logger.error("Неизвестный тип отложенной задачи: %s", task["kind"])
            continue
        try:
            await executor(bot, task)
            done += 1
        except Exception:
            logger.exception(
                "Отложенная задача %s (%s) не выполнена", task["id"], task["kind"]
            )
    return done


async def run_scheduled_loop(bot):
    global _wake
    _wake = asyncio.Event()
    while True:
        _wake.clear()  # до запроса: schedule() во время обработки не потеряется
        next_run = None
        try:
            await process_due(bot)
            next_run = await next_scheduled_run_at()
        except Exception:
            logger.exception("Сбой цикла отложенных задач")
        delay = _MAX_SLEEP
        if next_run is not None:
            delay = min(_MAX_SLEEP, next_run - time.time())
        with suppress(TimeoutError):
            await asyncio.wait_for(_wake.wait(), max(_MIN_SLEEP, delay))
