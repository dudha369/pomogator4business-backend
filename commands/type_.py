import asyncio

from app.platform.telegram.context import CommandContext
from app.platform.telegram.registry import command
from db.models.message_log import log_message
from core.utils import log_suppressed

TYPE_TRIGGERS = ["_type", "=type", "-type", "#type", ">type", "|type"]

_CURSORS = {
    "_type": "_",
    "=type": "=",
    "-type": "-",
    "#type": "#",
    ">type": "▌",
    "|type": "|",
}

_DEFAULT_CURSOR = "▌"
_MAX_STEPS = 20
_STEP_DELAY = 0.2


def _build_steps(text: str):
    length = len(text)
    if length <= _MAX_STEPS:
        return [text[: i + 1] for i in range(length)]

    step = max(1, length // _MAX_STEPS)
    cut_points = list(range(step, length, step))
    if cut_points[-1] != length:
        cut_points.append(length)
    return [text[:i] for i in cut_points]


async def typewriter(bot, connection, chat_id, text, cursor, message_id=None):
    steps = _build_steps(text)

    if message_id is None:
        sent = await bot.send_message(
            business_connection_id=connection["connection_id"],
            chat_id=chat_id,
            text=cursor,
            parse_mode=None,
        )
        message_id = sent.message_id
        await log_message(connection["connection_id"], chat_id, message_id)
    else:
        try:
            await bot.edit_message_text(
                business_connection_id=connection["connection_id"],
                chat_id=chat_id,
                message_id=message_id,
                text=cursor,
                parse_mode=None,
            )
        except Exception:
            log_suppressed("commands/type_.py:54", benign=True)

    for step_text in steps:
        await asyncio.sleep(_STEP_DELAY)
        try:
            await bot.edit_message_text(
                business_connection_id=connection["connection_id"],
                chat_id=chat_id,
                message_id=message_id,
                text=step_text + cursor,
                parse_mode=None,
            )
        except Exception:
            log_suppressed("commands/type_.py:66", benign=True)

    try:
        await bot.edit_message_text(
            business_connection_id=connection["connection_id"],
            chat_id=chat_id,
            message_id=message_id,
            text=text,
            parse_mode=None,
        )
    except Exception:
        log_suppressed("commands/type_.py:76", benign=True)


async def handle_type_trigger(bot, message, connection, trigger):
    if message.from_user.id != connection["owner_id"]:
        return

    text = (message.text or "")[len(trigger) :].strip()
    if not text:
        return

    cursor = _CURSORS.get(trigger, _DEFAULT_CURSOR)

    await typewriter(bot, connection, message.chat.id, text, cursor, message.message_id)


@command(name="type", module="type")
async def cmd_type(ctx: CommandContext):
    if not ctx.args:
        return

    await typewriter(
        ctx.bot,
        ctx.connection,
        ctx.chat_id,
        ctx.args,
        _DEFAULT_CURSOR,
        ctx.message.message_id,
    )
