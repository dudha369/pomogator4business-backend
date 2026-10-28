import pytest

from core import database as db
from core import reminders as rem

from .conftest import CONNECTION_ID, NOW, OWNER_ID

H = 3600


def row(chat, owner, ts, mid):
    return {"chat_id": chat, "is_owner": owner, "created_at": ts, "message_id": mid}


# ----------------------------- чистая логика --------------------------------


def test_waiting_only_when_last_message_is_incoming_and_old_enough():
    rows = [
        row(1, False, NOW - 6 * H, 1),  # ждёт 6 ч
        row(2, False, NOW - 6 * H, 1),
        row(2, True, NOW - 5 * H, 2),  # ответили
        row(3, False, NOW - 1 * H, 1),  # ещё рано
        row(4, False, NOW - 10 * 86400, 1),  # слишком давно
        row(5, False, NOW - 9 * H, 1),
        row(5, False, NOW - 8 * H, 2),  # серия: считаем от... последнего
    ]
    got = rem.compute_waiting(rows, NOW, 4 * H)
    assert [(w["chat_id"], w["message_id"]) for w in got] == [(5, 2), (1, 1)]
    assert got[0]["waited_seconds"] == 8 * H


def test_waited_formatting():
    from core.i18n import t  # noqa: F401

    assert rem.format_waited(30 * 60, "ru") == "30 мин"
    assert rem.format_waited(5 * H + 20 * 60, "ru") == "5 ч 20 мин"
    assert rem.format_waited(26 * H, "ru") == "1 д 2 ч"
    assert rem.format_waited(10, "en") == "1 min"


def test_quiet_hours():
    day = NOW - (NOW % 86400)
    at = lambda h: day + h * 3600  # noqa: E731
    assert rem.is_quiet(at(23), 0, 22 * 60, 8 * 60) and rem.is_quiet(
        at(3), 0, 22 * 60, 8 * 60
    )
    assert not rem.is_quiet(at(12), 0, 22 * 60, 8 * 60)
    assert not rem.is_quiet(at(23), 0, None, None) and not rem.is_quiet(
        at(23), 0, 600, 600
    )


# ------------------------------- сценарии -----------------------------------


@pytest.fixture
async def setup(connection, bot):
    await db.set_timezone_offset(OWNER_ID, 0)
    await db.upsert_reminder_settings(OWNER_ID, enabled=True, hours=4)
    bot.chat_names = {7: ("Аня <b>", "anya"), 8: ("Борис", None)}
    return connection


async def seed(chat, mid, ts, text, owner=False):
    await db.save_history(CONNECTION_ID, chat, mid, owner, text, ts)


async def tick(bot, now=NOW):
    return await rem.process_owner(bot, OWNER_ID, now=now)


async def test_reminds_once_per_series_and_escapes(setup, bot):
    await seed(7, 1, NOW - 6 * H, "Привет <script>alert(1)</script>")
    assert await tick(bot) == 1
    msg = bot.sent[-1]
    assert msg["chat_id"] == OWNER_ID and msg["parse_mode"] == "html"
    assert "<script>" not in msg["text"] and "&lt;script&gt;" in msg["text"]
    assert "Аня &lt;b&gt;" in msg["text"] and "https://t.me/anya" in msg["text"]
    assert "6 ч" in msg["text"]

    assert await tick(bot, NOW + 600) == 0  # та же серия — молчим
    await seed(7, 2, NOW + 100, "Ты тут?")
    assert await tick(bot, NOW + 100 + 5 * H) == 1  # новое сообщение — новая серия


async def test_answered_chat_not_reminded(setup, bot):
    await seed(7, 1, NOW - 6 * H, "Привет")
    await seed(7, 2, NOW - 5 * H, "Привет!", owner=True)
    assert await tick(bot) == 0 and bot.sent == []


async def test_disabled_or_quiet_or_no_connection(setup, bot):
    await seed(7, 1, NOW - 6 * H, "Привет")
    await db.upsert_reminder_settings(
        OWNER_ID, quiet_start_minutes=0, quiet_end_minutes=1439
    )
    assert await tick(bot) == 0  # тихие часы
    await db.upsert_reminder_settings(
        OWNER_ID, quiet_start_minutes=None, quiet_end_minutes=None, enabled=False
    )
    assert await tick(bot) == 0  # выключено
    await db.upsert_reminder_settings(OWNER_ID, enabled=True)
    assert await tick(bot) == 1  # после тихих часов напомнит
    assert (
        await rem.process_owner(bot, 999, now=NOW) == 0
    )  # чужой владелец без подключения


async def test_chat_flag_and_favorites_only(setup, bot):
    await seed(7, 1, NOW - 6 * H, "a")
    await seed(8, 1, NOW - 7 * H, "b")
    await db.set_chat_flags(OWNER_ID, 7, no_remind=True)
    assert (
        await tick(bot) == 1
        and "Борис" in bot.sent[-1]["text"]
        and "Аня" not in bot.sent[-1]["text"]
    )

    await db.set_chat_flags(OWNER_ID, 7, no_remind=False)
    await db.upsert_reminder_settings(OWNER_ID, favorites_only=True)
    await db.set_favorite_chat(OWNER_ID, 7, True)
    sent_before = len(bot.sent)
    assert (
        await tick(bot, NOW + 60) == 1 and len(bot.sent) == sent_before + 1
    )  # только избранный 7


async def test_failed_send_is_retried_next_time(setup, bot, monkeypatch):
    await seed(7, 1, NOW - 6 * H, "a")

    async def boom(**kw):
        raise RuntimeError("telegram")

    original = bot.send_message
    monkeypatch.setattr(bot, "send_message", boom)
    assert await tick(bot) == 0
    monkeypatch.setattr(bot, "send_message", original)
    assert await tick(bot, NOW + 600) == 1  # не записали в журнал — повторили


async def test_long_list_is_capped(setup, bot):
    for chat in range(100, 115):
        await seed(chat, 1, NOW - 6 * H, f"m{chat}")
    bot.chat_names = None
    assert await tick(bot) == 15
    text = bot.sent[-1]["text"]
    assert text.count("• ") == rem.MAX_LINES and "ещё 5" in text


# ----------------------------------- API ------------------------------------


async def test_reminders_api(client):
    h = client.owner
    r = await client.post(
        "/api/reminders",
        headers=h,
        json={
            "enabled": True,
            "hours": 2,
            "quiet_start_minutes": 1320,
            "quiet_end_minutes": 480,
        },
    )
    assert r.json() == {
        "enabled": True,
        "hours": 2,
        "quiet_start_minutes": 1320,
        "quiet_end_minutes": 480,
        "favorites_only": False,
    }
    assert (
        await client.post("/api/reminders", headers=h, json={"hours": 0})
    ).status_code == 422
    assert (
        await client.post(
            "/api/reminders", headers=h, json={"quiet_start_minutes": 2000}
        )
    ).status_code == 422
    cleared = await client.post(
        "/api/reminders",
        headers=h,
        json={"quiet_start_minutes": None, "quiet_end_minutes": None},
    )
    assert (
        cleared.json()["quiet_start_minutes"] is None and cleared.json()["hours"] == 2
    )


async def test_waiting_endpoint_and_command(client, bot, api_bot):
    import time

    now = int(time.time())
    await db.save_history(CONNECTION_ID, 7, 1, False, "Когда?", now - 5 * H)
    body = (await client.get("/api/reminders/waiting", headers=client.owner)).json()
    assert [c["chat_id"] for c in body["chats"]] == [7]


async def test_waiting_command_sends_list_privately(connection, bot):
    from core.context import CommandContext
    from modules.reminders import cmd_waiting

    from .conftest import make_message

    await db.save_history(CONNECTION_ID, 7, 1, False, "Когда будет?", NOW - 5 * H)
    import time

    # история «5 часов назад» относительно реального времени команды
    await db.save_history(
        CONNECTION_ID, 8, 1, False, "Ответьте", int(time.time()) - 5 * H
    )
    ctx = CommandContext(
        bot=bot,
        message=make_message(".waiting 2h", chat_id=OWNER_ID, from_id=OWNER_ID),
        connection=connection,
        args="2h",
        locale="ru",
        dm=True,
    )
    await cmd_waiting(ctx)
    assert bot.sent[-1]["chat_id"] == OWNER_ID and "Ответьте" in bot.sent[-1]["text"]
    assert bot.sent[-1]["parse_mode"] == "html"

    ctx.args = "bad"
    await cmd_waiting(ctx)
    assert "Формат" in bot.sent[-1]["text"]
