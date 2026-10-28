"""Шаблоны, флаги чатов, статистика, бэкап настроек, команды в личке."""

import types

from core import database as db
from core import stats
from handlers.bot_commands import on_dm_command, split_command
from modules.readall import cmd_readall
from core.readall import ReadFilter, parse_filters, select_chats
from handlers.business_messages import on_business_message

from .conftest import CONNECTION_ID, NOW, OWNER_ID, make_message

# --------------------------------- шаблоны ----------------------------------


async def test_template_command_replaces_message_and_hides_list(connection, bot):
    await db.save_template(OWNER_ID, "hello", "Здравствуйте, {name}!")
    await db.disable_module(CONNECTION_ID, "scam")

    await on_business_message(
        make_message(".t hello", chat_id=7, from_id=OWNER_ID, first_name="Аня"), bot
    )
    assert bot.edited and bot.edited[0]["text"] == "Здравствуйте, Аня!"

    bot.edited.clear()
    await on_business_message(make_message(".t", chat_id=7, from_id=OWNER_ID), bot)
    # список и ошибки уходят владельцу в личку, а не в чат с собеседником
    assert (
        bot.edited == []
        and bot.sent[-1]["chat_id"] == OWNER_ID
        and "hello" in bot.sent[-1]["text"]
    )
    await on_business_message(make_message(".t nope", chat_id=7, from_id=OWNER_ID), bot)
    assert bot.sent[-1]["chat_id"] == OWNER_ID and "nope" in bot.sent[-1]["text"]


async def test_template_api(client):
    h = client.owner
    r = await client.post(
        "/api/templates",
        headers=h,
        json={"name": " Привет ", "text": "Добрый день, {name}"},
    )
    assert r.json()["name"] == "привет"
    assert (
        await client.post(
            "/api/templates", headers=h, json={"name": "a b", "text": "x"}
        )
    ).status_code == 400
    assert (
        await client.post("/api/templates", headers=h, json={"name": "x", "text": "  "})
    ).status_code == 422
    assert len((await client.get("/api/templates", headers=h)).json()["templates"]) == 1
    assert (await client.delete("/api/templates/привет", headers=h)).status_code == 200
    assert (await client.delete("/api/templates/привет", headers=h)).status_code == 404


# ------------------------------- флаги чатов --------------------------------


async def test_noauto_command_toggles_and_confirms_privately(connection, bot):
    await db.disable_module(CONNECTION_ID, "scam")
    msg = lambda: make_message(".noauto", chat_id=7, from_id=OWNER_ID)  # noqa: E731
    await on_business_message(msg(), bot)
    assert (await db.get_chat_flags(OWNER_ID, 7))["no_autoreply"] is True
    assert bot.sent[-1]["chat_id"] == OWNER_ID
    await on_business_message(msg(), bot)
    assert (await db.get_chat_flags(OWNER_ID, 7)) == {
        "no_autoreply": False,
        "no_ai": False,
        "no_remind": False,
    }


async def test_chat_flags_api_is_partial(client):
    h = client.owner
    await client.post("/api/chat-flags", headers=h, json={"chat_id": 7, "no_ai": True})
    r = await client.post(
        "/api/chat-flags", headers=h, json={"chat_id": 7, "no_autoreply": True}
    )
    assert r.json() == {
        "chat_id": 7,
        "no_autoreply": True,
        "no_ai": True,
        "no_remind": False,
    }
    r = await client.post(
        "/api/chat-flags",
        headers=h,
        json={"chat_id": 7, "no_autoreply": False, "no_ai": False},
    )
    assert (await client.get("/api/chat-flags", headers=h)).json() == {"chats": []}


# --------------------------------- статистика -------------------------------


def row(chat, owner, ts, mid=0):
    return {"chat_id": chat, "is_owner": owner, "created_at": ts, "message_id": mid}


def test_reply_times_per_chat_with_streaks():
    rows = [
        row(1, False, 100),
        row(1, False, 130),
        row(1, True, 400),  # 300 с от ПЕРВОГО неотвеченного
        row(2, False, 200),
        row(2, True, 260),  # 60 с
        row(3, True, 500),  # ответ без входящего — не считается
        row(1, False, 1000),
        row(1, True, 1000 + 25 * 3600),  # дольше суток — не считается
    ]
    assert sorted(stats.reply_times(rows)) == [60, 300]
    summary = stats.reply_summary(stats.reply_times(rows))
    assert summary["median_seconds"] == 180 and summary["samples"] == 2
    assert stats.reply_summary([]) == {
        "median_seconds": None,
        "p90_seconds": None,
        "samples": 0,
    }


def test_daily_activity_fills_gaps_and_respects_timezone():
    now = NOW - (NOW % 86400) + 3600  # 01:00 UTC
    rows = [row(1, False, now), row(1, True, now - 86400)]
    result = stats.daily_activity(rows, now, 0, 3)
    assert [d["incoming"] + d["outgoing"] for d in result] == [0, 1, 1] and len(
        result
    ) == 3
    # в UTC-5 «сегодня» ещё вчерашние сутки по UTC: оба сообщения попадают на другие даты
    shifted = stats.daily_activity(rows, now, -300, 3)
    assert shifted[-1]["date"] != result[-1]["date"]


def test_top_chats_ranking():
    rows = [row(1, False, 1)] * 3 + [row(2, False, 1)] + [row(2, True, 2)] * 3
    assert [c["chat_id"] for c in stats.top_chats(rows)] == [2, 1]


async def test_overview_endpoint(client):
    import time

    now = int(time.time())
    await db.save_history(CONNECTION_ID, 7, 1, False, "a", now - 120)
    await db.save_history(CONNECTION_ID, 7, 2, True, "b", now - 60)
    await db.log_archive_event(CONNECTION_ID, 7, 1, "deleted", "a", None, now - 30)
    body = (await client.get("/api/stats/overview?days=7", headers=client.owner)).json()
    assert len(body["days"]) == 7 and body["top_chats"][0]["chat_id"] == 7
    assert body["archive"] == {"deleted": 1, "edited": 0}
    assert (
        body["reply_time"]["samples"] == 1
        and body["reply_time"]["median_seconds"] == 60
    )
    assert (
        await client.get("/api/stats/overview?days=0", headers=client.owner)
    ).status_code == 422


# ------------------------------------ бэкап ---------------------------------


async def test_backup_roundtrip_and_hardening(client):
    h = client.owner
    await client.post(
        "/api/autoresponder",
        headers=h,
        json={"greeting_enabled": True, "greeting_text": "Привет"},
    )
    await client.post(
        "/api/autoresponder/keywords",
        headers=h,
        json={"keyword": "цена", "reply_text": "100"},
    )
    await client.post("/api/templates", headers=h, json={"name": "t1", "text": "text"})
    await client.post(
        "/api/aliases", headers=h, json={"command": "ping", "alias": "пп"}
    )
    await client.post(
        "/api/favorites", headers=h, json={"chat_id": 7, "favorite": True}
    )
    await db.disable_module(CONNECTION_ID, "echo")
    backup = (await client.get("/api/backup/export", headers=h)).json()
    assert backup["version"] == 1 and "token" not in str(backup).lower()

    # «чистая» БД: удаляем всё и восстанавливаем
    await client.delete("/api/autoresponder/keywords/цена", headers=h)
    await client.delete("/api/templates/t1", headers=h)
    await client.delete("/api/aliases/пп", headers=h)
    await client.post(
        "/api/favorites", headers=h, json={"chat_id": 7, "favorite": False}
    )
    await db.enable_module(CONNECTION_ID, "echo")

    r = await client.post("/api/backup/import", headers=h, json=backup)
    assert r.status_code == 200 and r.json()["skipped"] == 0
    assert (await client.get("/api/autoresponder", headers=h)).json()["keywords"][0][
        "keyword"
    ] == "цена"
    assert (await client.get("/api/favorites", headers=h)).json() == {"chat_ids": [7]}
    assert await db.list_disabled_modules(CONNECTION_ID) == {"echo"}
    assert (await client.get("/api/aliases", headers=h)).json()["aliases"][0][
        "alias"
    ] == "пп"


async def test_backup_import_skips_bad_items_and_never_enables_ai(client):
    h = client.owner
    bad = {
        "version": 1,
        "disabled_modules": ["echo", "no-such-module"],
        "aliases": [
            {"alias": "ping", "command": "ping"},
            {"alias": "ok1", "command": "nope"},
        ],
        "templates": [{"name": "a b", "text": "x"}],
        "keywords": [{"keyword": " ", "reply_text": "x"}],
        "autoresponder": {
            "away_enabled": True,
            "away_text": "",
        },  # без текста — не включаем
        "ai": {"enabled": True, "mode": "auto", "daily_limit": 9999},
    }
    r = await client.post("/api/backup/import", headers=h, json=bad)
    assert r.status_code == 200 and r.json()["skipped"] >= 5
    assert (await client.get("/api/autoresponder", headers=h)).json()[
        "away_enabled"
    ] is False
    state = (await client.get("/api/ai", headers=h)).json()
    assert (
        state["enabled"] is False
        and state["mode"] == "auto"
        and state["daily_limit"] == 30
    )
    assert (
        await client.post("/api/backup/import", headers=h, json={"version": 2})
    ).status_code == 422


# ------------------------- команды в личке и readall ------------------------


def test_split_command_variants():
    assert split_command("/readall@mybot 6h nofav", ".") == ("readall", "6h nofav")
    assert split_command(".ping", ".") == ("ping", "")
    assert split_command("привет", ".") is None and split_command("/", ".") is None


def test_readall_filters():
    flt = parse_filters("6h >2d nofav")
    assert (flt.last_seconds, flt.older_seconds, flt.exclude_fav) == (
        6 * 3600,
        2 * 86400,
        True,
    )
    assert parse_filters("zzz") is None and parse_filters("") == ReadFilter()
    rows = [
        {"chat_id": 1, "last_at": NOW - 600},
        {"chat_id": 2, "last_at": NOW - 30 * 3600},
    ]
    pick = lambda args, fav=frozenset(): sorted(  # noqa: E731
        r["chat_id"] for r in select_chats(rows, NOW, fav, parse_filters(args))
    )
    assert pick("") == [1, 2] and pick("2h") == [1] and pick(">24h") == [2]
    assert pick("nofav", {1}) == [2]


def dm(text, user_id=OWNER_ID):
    answers = []

    async def answer(t, **kw):
        answers.append(t)

    msg = types.SimpleNamespace(
        text=text,
        from_user=types.SimpleNamespace(id=user_id),
        answer=answer,
        chat=types.SimpleNamespace(id=user_id, type="private"),
        message_id=9,
        date=make_message().date,
    )
    return msg, answers


async def test_dm_readall_and_ping(connection, bot):
    await db.save_history(CONNECTION_ID, 7, 71, False, "a", NOW - 100)
    msg, answers = dm("/readall")
    await on_dm_command(msg, bot)
    assert bot.reads[0]["chat_id"] == 7
    assert bot.sent[-1]["chat_id"] == OWNER_ID and "1" in bot.sent[-1]["text"]

    msg, _ = dm("/ping")
    await on_dm_command(msg, bot)
    assert "pong" in bot.sent[-1]["text"]


async def test_dm_guards(connection, bot):
    msg, answers = dm("/fav")  # команда только для чатов
    await on_dm_command(msg, bot)
    assert len(answers) == 1 and bot.sent == []
    msg, answers = dm("/ping", user_id=999)  # нет подключения
    await on_dm_command(msg, bot)
    assert len(answers) == 1 and bot.sent == []
    await db.disable_module(CONNECTION_ID, "ping")  # модуль выключен
    msg, answers = dm("/ping")
    await on_dm_command(msg, bot)
    assert len(answers) == 1 and bot.sent == []
    msg, answers = dm("/unknowncmd")  # чужая команда — молчим
    await on_dm_command(msg, bot)
    assert answers == []
