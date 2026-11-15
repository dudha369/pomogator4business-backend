"""Персистентные .timer / .bomb (core/scheduled.py)."""

import asyncio
import time

import pytest

from db.models.scheduled_task import (
    add_scheduled_task,
    claim_scheduled_task,
    list_due_scheduled_tasks,
)
from core import scheduled
from app.platform.telegram.context import CommandContext
from modules.bomb import cmd_bomb
from modules.timer import cmd_timer

from .conftest import CONNECTION_ID, FakeBot, make_message


def make_ctx(bot, connection, args="", reply_to=None):
    msg = make_message(".x", chat_id=7, from_id=42)
    if reply_to is not None:
        msg.reply_to_message = reply_to
    return CommandContext(bot=bot, message=msg, connection=connection, args=args)


async def test_timer_is_stored_and_fires_once(connection):
    bot = FakeBot()
    await cmd_timer(make_ctx(bot, connection, "1m привет <b>"))
    rows = await list_due_scheduled_tasks(int(time.time()) + 61)
    assert len(rows) == 1 and rows[0]["kind"] == "timer"
    assert await list_due_scheduled_tasks(int(time.time())) == []  # ещё рано

    now = int(time.time()) + 61
    assert await scheduled.process_due(bot, now) == 1
    assert await scheduled.process_due(bot, now) == 0  # второй раз не уходит
    assert bot.sent[-1]["text"] == "привет <b>"
    assert bot.sent[-1]["parse_mode"] is None
    assert bot.sent[-1]["chat_id"] == 7


async def test_overdue_after_downtime_is_executed(connection):
    """Рестарт/сон Render: задача просрочена — выполняется при старте."""
    await add_scheduled_task("timer", CONNECTION_ID, 7, 1000, text="поздно")
    bot = FakeBot()
    assert await scheduled.process_due(bot) == 1
    assert bot.sent[-1]["text"] == "поздно"


async def test_bomb_on_reply_deletes_target_message(connection):
    bot = FakeBot()
    target = make_message("цель", chat_id=7, from_id=42)
    await cmd_bomb(make_ctx(bot, connection, "30s", reply_to=target))
    await scheduled.process_due(bot, int(time.time()) + 31)
    assert any(target.message_id in d["message_ids"] for d in bot.deleted)


async def test_bomb_with_text_edits_then_deletes_itself(connection):
    bot = FakeBot()
    ctx = make_ctx(bot, connection, "10s взрыв")
    await cmd_bomb(ctx)
    assert bot.edited[-1]["text"] == "взрыв"
    await scheduled.process_due(bot, int(time.time()) + 11)
    assert bot.deleted[-1]["message_ids"] == [ctx.message.message_id]


async def test_claim_is_exclusive(connection):
    row = await add_scheduled_task("timer", CONNECTION_ID, 7, 1, text="x")
    assert await claim_scheduled_task(row.id) is True
    assert await claim_scheduled_task(row.id) is False


async def test_failed_executor_does_not_block_others(connection):
    await add_scheduled_task("bomb", CONNECTION_ID, 7, 1, message_id=1)
    await add_scheduled_task("timer", CONNECTION_ID, 7, 2, text="ok")

    class Boom(FakeBot):
        async def delete_business_messages(self, **kw):
            raise RuntimeError("telegram down")

    bot = Boom()
    await scheduled.process_due(bot, 10)
    assert bot.sent[-1]["text"] == "ok"
    assert await list_due_scheduled_tasks(10) == []  # ничего не зависло


async def test_unknown_kind_is_dropped(connection):
    await add_scheduled_task("???", CONNECTION_ID, 7, 1)
    assert await scheduled.process_due(FakeBot(), 10) == 0
    assert await list_due_scheduled_tasks(10) == []


async def test_loop_wakes_up_for_new_earlier_task(connection):
    bot = FakeBot()
    loop_task = asyncio.create_task(scheduled.run_scheduled_loop(bot))
    try:
        await asyncio.sleep(0.05)  # цикл ушёл спать (задач нет)
        await scheduled.schedule("timer", CONNECTION_ID, 7, 0, text="сразу")
        for _ in range(50):
            if bot.sent:
                break
            await asyncio.sleep(0.02)
        assert bot.sent and bot.sent[-1]["text"] == "сразу"
    finally:
        loop_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await loop_task
