import types

import pytest

from config import settings
from core import ai
from core import autoresponder as ar
from core import database as db
from handlers.ai_drafts import on_draft_button

from .conftest import CONNECTION_ID, NOW, OWNER_ID, make_message

NOON = NOW - (NOW % 86400) + 12 * 3600


@pytest.fixture
def ai_on(monkeypatch):
    """Ключ задан, провайдер подменён: запоминаем, что ему отправили."""
    monkeypatch.setattr(settings, "AI_API_KEY", "test-key")
    calls = []

    async def fake_complete(system, messages):
        calls.append({"system": system, "messages": messages})
        return "Конечно, давайте обсудим."

    monkeypatch.setattr(ai, "complete", fake_complete)
    return calls


async def enable_ai(mode="draft", **extra):
    await db.upsert_ai_settings(OWNER_ID, enabled=True, mode=mode, **extra)


async def deliver(connection, bot, text, chat=7, now=NOON, **kw):
    msg = make_message(text, chat_id=chat, from_id=chat, **kw)
    await db.save_history(CONNECTION_ID, chat, msg.message_id, False, text, now)
    reply = await ar.handle_incoming(bot, connection, msg, now=now)
    return reply.kind if reply else None


# ----------------------------- сборка запроса -------------------------------


def test_build_messages_alternates_and_starts_with_user():
    rows = [
        {
            "is_owner": True,
            "text": "Привет!",
            "message_id": 1,
        },  # ведущий assistant отбрасывается
        {"is_owner": False, "text": "Добрый день", "message_id": 2},
        {
            "is_owner": False,
            "text": "Есть вопрос",
            "message_id": 3,
        },  # склеивается с предыдущим
        {"is_owner": True, "text": "Слушаю", "message_id": 4},
        {"is_owner": False, "text": None, "message_id": 5},  # без текста — пропуск
        {
            "is_owner": False,
            "text": "Текущее",
            "message_id": 6,
        },  # само текущее — не дублируем
    ]
    messages = ai.build_messages(rows, "Текущее", current_message_id=6)
    assert [m["role"] for m in messages] == ["user", "assistant", "user"]
    assert messages[0]["content"] == "Добрый день\nЕсть вопрос"
    assert messages[-1]["content"] == "Текущее"


def test_build_messages_without_history():
    assert ai.build_messages([], " hi ") == [{"role": "user", "content": "hi"}]


def test_system_prompt_guards_against_injection_and_caps_instructions():
    prompt = ai.build_system_prompt("x" * 5000, "Андрей")
    assert "untrusted" in prompt and "Never invent" in prompt and "Андрей" in prompt
    assert len(prompt) < len(ai._SYSTEM_BASE) + ai.MAX_INSTRUCTIONS_LENGTH + 200


# ------------------------------- сценарии -----------------------------------


async def test_disabled_by_default(connection, bot, ai_on):
    assert await deliver(connection, bot, "привет") is None
    assert ai_on == []


async def test_not_used_without_server_key(connection, bot, monkeypatch):
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    await enable_ai()
    assert await deliver(connection, bot, "привет") is None


async def test_draft_mode_notifies_owner_and_never_writes_to_contact(
    connection, bot, ai_on
):
    await enable_ai("draft", instructions="Говори вежливо")
    assert await deliver(connection, bot, "Можно записаться?") == "ai"
    assert len(bot.sent) == 1
    sent = bot.sent[0]
    assert sent["chat_id"] == OWNER_ID and "business_connection_id" not in sent
    assert "Конечно" in sent["text"] and "Можно записаться?" in sent["text"]
    buttons = sent["reply_markup"].inline_keyboard[0]
    assert [b.callback_data.split(":")[1] for b in buttons] == ["send", "no"]
    assert "Говори вежливо" in ai_on[0]["system"]


async def test_auto_mode_replies_to_contact(connection, bot, ai_on):
    await enable_ai("auto")
    assert await deliver(connection, bot, "Привет") == "ai"
    assert (
        bot.sent[0]["chat_id"] == 7
        and bot.sent[0]["business_connection_id"] == CONNECTION_ID
    )


async def test_rules_take_priority_over_ai(connection, bot, ai_on):
    await enable_ai("auto")
    await db.add_keyword_reply(OWNER_ID, "цена", "Прайс: 100")
    assert await deliver(connection, bot, "какая цена?") == "keyword"
    assert ai_on == []


async def test_daily_limit_and_chat_cooldown(connection, bot, ai_on):
    await db.set_timezone_offset(OWNER_ID, 0)
    await enable_ai("auto", daily_limit=2)
    assert await deliver(connection, bot, "a", chat=7) == "ai"
    assert (
        await deliver(connection, bot, "b", chat=7, now=NOON + 10) is None
    )  # пауза в чате
    assert await deliver(connection, bot, "c", chat=8) == "ai"  # другой чат — можно
    assert (
        await deliver(connection, bot, "d", chat=9, now=NOON + 100) is None
    )  # дневной лимит


async def test_flags_disable_ai(connection, bot, ai_on):
    await enable_ai("auto")
    await db.set_chat_flags(OWNER_ID, 7, no_ai=True)
    assert await deliver(connection, bot, "привет", chat=7) is None
    await db.set_chat_flags(OWNER_ID, 8, no_autoreply=True)
    assert await deliver(connection, bot, "привет", chat=8) is None
    assert await deliver(connection, bot, "привет", chat=9) == "ai"


async def test_provider_failure_is_silent(connection, bot, monkeypatch):
    monkeypatch.setattr(settings, "AI_API_KEY", "k")

    async def failing(system, messages):
        return None

    monkeypatch.setattr(ai, "complete", failing)
    await enable_ai("auto")
    assert await deliver(connection, bot, "привет") is None and bot.sent == []


async def test_commands_and_owner_activity_skip_ai(connection, bot, ai_on):
    await enable_ai("auto")
    assert await deliver(connection, bot, ".ping") is None
    await db.save_history(CONNECTION_ID, 12, 900, True, "я тут", NOON - 60)
    assert await deliver(connection, bot, "алло", chat=12) is None


# ------------------------------- кнопки -------------------------------------


class FakeCallback:
    def __init__(self, data, user_id=OWNER_ID):
        self.data = data
        self.from_user = types.SimpleNamespace(id=user_id)
        self.message = types.SimpleNamespace(text="черновик", edit_text=self._edit)
        self.answers, self.edits = [], []

    async def _edit(self, text, reply_markup=None):
        self.edits.append(text)

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)


async def make_draft(created_at=None):
    import time

    return await db.create_draft(
        OWNER_ID, 7, 5, "Готовый ответ", created_at or int(time.time())
    )


async def test_send_button_sends_once(connection, bot):
    draft_id = await make_draft()
    first = FakeCallback(f"aid:send:{draft_id}")
    await on_draft_button(first, bot)
    assert [m["text"] for m in bot.sent] == ["Готовый ответ"] and bot.sent[0][
        "chat_id"
    ] == 7
    assert first.edits and "✅" in first.edits[0]

    second = FakeCallback(f"aid:send:{draft_id}")  # двойное нажатие
    await on_draft_button(second, bot)
    assert len(bot.sent) == 1 and second.answers[0]


async def test_dismiss_and_foreign_user(connection, bot):
    draft_id = await make_draft()
    foreign = FakeCallback(f"aid:send:{draft_id}", user_id=999)
    await on_draft_button(foreign, bot)
    assert bot.sent == []  # чужой пользователь не может отправить

    await on_draft_button(FakeCallback(f"aid:no:{draft_id}"), bot)
    again = FakeCallback(f"aid:send:{draft_id}")
    await on_draft_button(again, bot)
    assert bot.sent == []  # отклонённый не отправить


async def test_expired_draft_is_not_sent(connection, bot):
    draft_id = await make_draft(created_at=1)
    cb = FakeCallback(f"aid:send:{draft_id}")
    await on_draft_button(cb, bot)
    assert bot.sent == [] and (await db.get_draft(draft_id))["status"] == "dismissed"


async def test_failed_send_keeps_draft_pending(connection, bot, monkeypatch):
    async def boom(**kw):
        raise RuntimeError("telegram")

    monkeypatch.setattr(bot, "send_message", boom)
    draft_id = await make_draft()
    await on_draft_button(FakeCallback(f"aid:send:{draft_id}"), bot)
    assert (await db.get_draft(draft_id))["status"] == "pending"


# --------------------------------- API --------------------------------------


async def test_ai_api_requires_server_key_to_enable(client, monkeypatch):
    monkeypatch.setattr(settings, "AI_API_KEY", "")
    r = await client.post("/api/ai", headers=client.owner, json={"enabled": True})
    assert r.status_code == 409
    state = (await client.get("/api/ai", headers=client.owner)).json()
    assert state["configured"] is False and state["enabled"] is False


async def test_ai_api_validation_and_state(client, ai_on):
    h = client.owner
    r = await client.post(
        "/api/ai",
        headers=h,
        json={
            "enabled": True,
            "mode": "auto",
            "daily_limit": 5,
            "instructions": "Кратко",
        },
    )
    assert (
        r.status_code == 200
        and r.json()["mode"] == "auto"
        and r.json()["daily_limit"] == 5
    )
    assert (
        await client.post("/api/ai", headers=h, json={"mode": "robot"})
    ).status_code == 422
    assert (
        await client.post("/api/ai", headers=h, json={"daily_limit": 0})
    ).status_code == 422
    r = await client.post("/api/ai", headers=h, json={"instructions": None})
    assert r.json()["instructions"] is None and r.json()["mode"] == "auto"


async def test_ai_test_endpoint(client, ai_on):
    r = await client.post("/api/ai/test", headers=client.owner, json={"text": "Привет"})
    assert r.json() == {"reply": "Конечно, давайте обсудим."}
    assert ai_on[0]["messages"] == [{"role": "user", "content": "Привет"}]
