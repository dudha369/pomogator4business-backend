"""Регрессии чата «Баги A» (HANDOFF_audit, раздел 2, пп. 1–11)."""

from typing import ClassVar

import pytest

from app.features.games.bot.guess_number import cmd_guess
from app.features.games.service import get_game, save_game
from app.features.history.service import log_message, recent_message_log
from app.features.mirror.queries import get_mirror
from app.features.profile.service import get_profile_backup
from app.features.voice_effects.queries import set_voice_effect
from app.platform.telegram.context import CommandContext

from .conftest import FakeBot, make_message


def make_ctx(bot, connection, args="", text=".x", from_id=42):
    msg = make_message(text, chat_id=7, from_id=from_id)
    return CommandContext(bot=bot, message=msg, connection=connection, args=args)


# --- 1. ctx.answer не существует ---------------------------------------------
async def test_guess_replies_with_ctx_reply(connection):
    bot = FakeBot()
    await cmd_guess(make_ctx(bot, connection, "10"))
    assert bot.sent, "команда .guess должна ответить"


# --- 11. переполнение INT в .guess -------------------------------------------
@pytest.mark.parametrize("raw", ["9" * 30, "9" * 5000, "²³"])
async def test_guess_huge_number_does_not_crash(connection, raw):
    bot = FakeBot()
    await cmd_guess(make_ctx(bot, connection, raw))  # не должно упасть
    assert bot.sent


async def test_guess_huge_max_is_capped(connection):

    bot = FakeBot()
    await cmd_guess(make_ctx(bot, connection, "9" * 30))
    game = await get_game("guess", "conn-1", 7)
    assert game["max_value"] == 1_000_000_000


async def test_huge_guess_in_active_game_is_just_too_high(connection):

    bot = FakeBot()
    await cmd_guess(make_ctx(bot, connection, "50"))
    await cmd_guess(make_ctx(bot, connection, "9" * 5000))
    game = await get_game("guess", "conn-1", 7)
    assert game["status"] == "active" and game["attempts"] == 1


# --- 2. неэкранированный пользовательский текст при глобальном parse_mode=HTML ---
def effective_parse_mode(kwargs):
    """Глобального parse_mode больше нет: без явного значения разметки нет."""
    return kwargs.get("parse_mode")


EVIL = "a <b> & <i>x"


async def test_8ball_escapes_question(connection):
    from commands.eightball import cmd_8ball

    bot = FakeBot()
    await cmd_8ball(make_ctx(bot, connection, EVIL))
    text = bot.edited[-1]["text"]
    assert "a &lt;b&gt; &amp; &lt;i&gt;x" in text and EVIL not in text


@pytest.mark.parametrize(
    "module, func, args",
    [
        ("commands.bomb", "cmd_bomb", f"10s {EVIL}"),
        ("commands.split", "cmd_split", EVIL),
        ("commands.type_", "cmd_type", EVIL),
        ("commands.plove", "cmd_plove", EVIL),
    ],
)
async def test_verbatim_commands_send_plain_text(
    connection, monkeypatch, module, func, args
):
    import asyncio
    import importlib

    mod = importlib.import_module(module)
    real_sleep = asyncio.sleep

    async def fast_sleep(_delay, *a, **kw):
        await real_sleep(0)

    monkeypatch.setattr(asyncio, "sleep", fast_sleep)
    bot = FakeBot()
    await getattr(mod, func)(make_ctx(bot, connection, args))
    await real_sleep(0.05)  # дать отработать фоновым таймерам
    calls = [c for c in bot.sent + bot.edited if "<" in c.get("text", "")]
    assert calls, "текст с < должен был уйти"
    assert all(effective_parse_mode(c) is None for c in calls)


async def test_spam_and_tr_send_plain_text(connection, monkeypatch):

    from commands import spam, tr

    monkeypatch.setattr(spam, "_DELAY", 0)
    bot = FakeBot()
    await spam.cmd_spam(make_ctx(bot, connection, f"2 {EVIL}"))
    assert len(bot.sent) == 2
    assert all(effective_parse_mode(c) is None for c in bot.sent)

    class _T:
        def __init__(self, **kw): ...
        def translate(self, text):
            return EVIL

    monkeypatch.setattr(tr, "GoogleTranslator", _T)
    bot = FakeBot()
    await tr.cmd_tr(make_ctx(bot, connection, "en привет"))
    assert effective_parse_mode(bot.edited[-1]) is None


async def test_archive_view_escapes_old_text(connection, monkeypatch):
    import types

    from app.features.settings import bot as settings

    async def fake_recent(*_a):
        return [{"event": "deleted", "chat_id": 7, "old_text": EVIL}]

    monkeypatch.setattr(settings, "get_recent_archive", fake_recent)
    answers = []

    async def answer(text, **kw):
        answers.append(text)

    msg = types.SimpleNamespace(from_user=types.SimpleNamespace(id=42), answer=answer)
    await settings.cmd_archive_view(msg)
    assert "&lt;b&gt;" in answers[-1] and "<b>" not in answers[-1]


# --- 10. префикс ---------------------------------------------------------------
@pytest.mark.parametrize(
    "prefix, ok",
    [
        (".", True),
        ("!", True),
        ("/", True),
        (" ", False),
        ("a", False),
        ("7", False),
        ("", False),
        ("..", False),
        ("я", False),
    ],
)
def test_is_valid_prefix(prefix, ok):
    from app.platform.utils import is_valid_prefix

    assert is_valid_prefix(prefix) is ok


async def test_new_prefix_handler_ignores_non_text():
    """Фото/стикер в состоянии ввода префикса: хендлер не должен падать на .text=None."""
    import types

    from app.features.settings.bot import router

    handler = next(
        h for h in router.message.handlers if h.callback.__name__ == "on_new_prefix"
    )
    text_filter = handler.filters[-1].callback  # F.text
    assert not text_filter(types.SimpleNamespace(text=None))
    assert text_filter(types.SimpleNamespace(text="!"))


# --- 3. потеря данных -----------------------------------------------------------
class OrderBot(FakeBot):
    """Запоминает порядок вызовов; fail_* имитируют отказ Telegram."""

    fail_send_voice = False
    fail_delete = False

    def __init__(self):
        super().__init__()
        self.order = []

    async def send_voice(self, **kw):
        self.order.append("send_voice")
        if self.fail_send_voice:
            raise RuntimeError("send failed")
        return await super().send_voice(**kw)

    async def delete_business_messages(self, **kw):
        self.order.append("delete")
        if self.fail_delete:
            raise RuntimeError("delete failed")
        return await super().delete_business_messages(**kw)


async def _voice_setup(connection, monkeypatch):
    import types

    from app.features.voice_effects import bot as voice_effects

    async def fake_filter(data, flt):
        return b"processed"

    monkeypatch.setattr(voice_effects, "apply_audio_filter", fake_filter)
    await set_voice_effect("conn-1", 7, "robot")
    msg = make_message(None, chat_id=7, from_id=42)
    msg.voice = types.SimpleNamespace(file_id="f")
    return voice_effects, msg


async def test_voice_effect_sends_before_deleting_original(connection, monkeypatch):
    voice_effects, msg = await _voice_setup(connection, monkeypatch)
    bot = OrderBot()
    assert await voice_effects.handle_voice_message(bot, connection, msg) is True
    assert bot.order == ["send_voice", "delete"]


async def test_voice_effect_keeps_original_if_send_fails(connection, monkeypatch):
    voice_effects, msg = await _voice_setup(connection, monkeypatch)
    bot = OrderBot()
    bot.fail_send_voice = True
    assert await voice_effects.handle_voice_message(bot, connection, msg) is False
    assert "delete" not in bot.order


async def test_panic_keeps_log_when_delete_fails(connection):
    from commands.panic import cmd_panic

    for mid in (1, 2, 3):
        await log_message("conn-1", 7, mid)
    bot = OrderBot()
    bot.fail_delete = True
    await cmd_panic(make_ctx(bot, connection, "3"))
    rows = await recent_message_log("conn-1", 7, 10)
    assert [mid for _, mid in rows] == [3, 2, 1], "журнал нужен для повтора"

    bot.fail_delete = False  # повтор проходит и стирает журнал
    await cmd_panic(make_ctx(bot, connection, "3"))
    assert bot.deleted[-1]["message_ids"] == [3, 2, 1]
    assert await recent_message_log("conn-1", 7, 10) == []


async def test_failed_self_delete_does_not_swallow_real_archive_event():
    from app.platform.telegram.self_actions import (
        consume_self_delete,
        delete_own_messages,
    )

    bot = OrderBot()
    bot.fail_delete = True
    assert await delete_own_messages(bot, "c", 1, [5]) is False
    assert consume_self_delete("c", 1, 5) is False  # метки нет
    bot.fail_delete = False
    assert await delete_own_messages(bot, "c", 1, [5]) is True
    assert consume_self_delete("c", 1, 5) is True


class ProfileBot(FakeBot):
    def __init__(self):
        super().__init__()
        self.names, self.bios, self.photos = [], [], []

    async def set_business_account_name(self, **kw):
        self.names.append(kw)

    async def set_business_account_bio(self, **kw):
        self.bios.append(kw)

    async def set_business_account_profile_photo(self, **kw):
        self.photos.append(kw)

    async def get_chat(self, chat_id):
        import types

        return types.SimpleNamespace(bio=f"bio-of-{chat_id}")


async def test_profile_second_run_keeps_original_backup(connection, monkeypatch):
    import types

    from app.features.profile import bot as profile

    async def avatar(bot, user_id):
        return f"photo-{user_id}".encode()

    monkeypatch.setattr(profile, "download_user_avatar", avatar)
    bot = ProfileBot()

    def run(target_id, name):
        ctx = make_ctx(bot, connection, "")
        ctx.message.from_user.first_name = "Андрей"
        ctx.message.reply_to_message = types.SimpleNamespace(
            from_user=types.SimpleNamespace(
                id=target_id, first_name=name, last_name=None
            )
        )
        return profile.cmd_profile(ctx)

    await run(100, "Аня")
    first = await get_profile_backup("conn-1")
    assert first["bio"] == "bio-of-42" and first["photo_data"] == b"photo-42"

    await run(200, "Боря")  # второй .profile: бэкап прежний, а не профиль Ани
    again = await get_profile_backup("conn-1")
    assert again["bio"] == "bio-of-42" and again["photo_data"] == b"photo-42"

    await profile.cmd_restore(make_ctx(bot, connection, ""))
    assert bot.bios[-1]["bio"] == "bio-of-42"
    assert await get_profile_backup("conn-1") is None  # после .restore — чисто

    await run(200, "Боря")  # теперь новый бэкап снова возможен
    assert (await get_profile_backup("conn-1"))["bio"] == "bio-of-42"


# --- 4/5. зеркало и сброс очереди вебхука ---------------------------------------
GOOD_TOKEN = "123456:" + "A" * 35
OTHER_TOKEN = "654321:" + "B" * 35


class MirrorBot:
    """Подмена aiogram.Bot для зеркал: помнит вызовы set/delete_webhook."""

    instances: ClassVar[list] = []
    fail_webhook = False

    def __init__(self, token, **kwargs):
        self.token = token
        self.webhooks, self.deleted_webhook, self.closed = [], False, False
        self.session = types_ns(close=self._close)
        MirrorBot.instances.append(self)

    async def _close(self):
        self.closed = True

    async def set_webhook(self, **kw):
        if MirrorBot.fail_webhook:
            raise RuntimeError("telegram said no")
        self.webhooks.append(kw)

    async def delete_webhook(self):
        self.deleted_webhook = True

    async def get_me(self):
        return types_ns(id=int(self.token.split(":")[0]), username="mirror_bot")


def types_ns(**kw):
    import types

    return types.SimpleNamespace(**kw)


@pytest.fixture
def mirror_env(monkeypatch):
    from app.features.mirror import manager as mm
    from app.features.mirror import setup as mirror_setup
    from config import settings

    MirrorBot.instances, MirrorBot.fail_webhook = [], False
    monkeypatch.setattr(mm, "Bot", MirrorBot)
    monkeypatch.setattr(mirror_setup, "AiogramBot", MirrorBot)
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "https://example.test")
    mm.mirror_manager._bots.clear()
    mm.mirror_manager._secrets.clear()
    yield mm.mirror_manager
    mm.mirror_manager._bots.clear()
    mm.mirror_manager._secrets.clear()


async def test_start_mirror_without_base_url_raises(mirror_env, monkeypatch):
    from app.features.mirror.manager import MirrorStartError
    from config import settings

    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "")
    with pytest.raises(MirrorStartError) as exc:
        await mirror_env.start_mirror(1, GOOD_TOKEN)
    assert exc.value.code == "no_webhook_url" and not mirror_env.is_running(1)


async def test_start_mirror_webhook_failure_raises_and_closes_session(mirror_env):
    from app.features.mirror.manager import MirrorStartError

    MirrorBot.fail_webhook = True
    with pytest.raises(MirrorStartError) as exc:
        await mirror_env.start_mirror(1, GOOD_TOKEN)
    assert exc.value.code == "webhook_failed"
    assert MirrorBot.instances[0].closed and not mirror_env.is_running(1)


async def test_start_mirror_same_token_is_idempotent(mirror_env):
    await mirror_env.start_mirror(1, GOOD_TOKEN)
    await mirror_env.start_mirror(1, GOOD_TOKEN)
    assert len(MirrorBot.instances) == 1


async def test_start_mirror_new_token_replaces_old(mirror_env):
    await mirror_env.start_mirror(1, GOOD_TOKEN)
    await mirror_env.start_mirror(1, OTHER_TOKEN)
    old, new = MirrorBot.instances
    assert mirror_env.get_bot(1) is new
    assert old.deleted_webhook and old.closed
    assert mirror_env.verify_secret(1, mirror_env._secrets[1])


async def test_failed_replacement_keeps_working_mirror(mirror_env):
    from app.features.mirror.manager import MirrorStartError

    await mirror_env.start_mirror(1, GOOD_TOKEN)
    MirrorBot.fail_webhook = True
    with pytest.raises(MirrorStartError):
        await mirror_env.start_mirror(1, OTHER_TOKEN)
    assert mirror_env.get_bot(1) is MirrorBot.instances[0]
    assert not MirrorBot.instances[0].deleted_webhook


async def test_mirror_start_does_not_drop_pending_on_deploy(mirror_env):
    await mirror_env.start_mirror(1, GOOD_TOKEN)  # так зовёт start_all
    assert MirrorBot.instances[0].webhooks[0]["drop_pending_updates"] is False


async def test_connect_mirror_saves_nothing_when_start_fails(
    connection, mirror_env, monkeypatch
):
    from app.features.mirror.setup import MirrorSetupError, connect_mirror

    MirrorBot.fail_webhook = True
    with pytest.raises(MirrorSetupError) as exc:
        await connect_mirror(42, GOOD_TOKEN)
    assert exc.value.code == "start_failed"
    assert await get_mirror(42) is None


async def test_api_mirror_connect_reports_start_failure(client, mirror_env):
    MirrorBot.fail_webhook = True
    r = await client.post(
        "/api/mirror/connect", headers=client.owner, json={"token": GOOD_TOKEN}
    )
    assert r.status_code == 503 and r.json()["detail"] == "start_failed"
    status = (await client.get("/api/mirror", headers=client.owner)).json()
    assert status["connected"] is False and status["running"] is False

    MirrorBot.fail_webhook = False
    r = await client.post(
        "/api/mirror/connect", headers=client.owner, json={"token": GOOD_TOKEN}
    )
    assert r.status_code == 200 and r.json()["connected"] is True
    status = (await client.get("/api/mirror", headers=client.owner)).json()
    assert status["running"] is True


async def test_mirror_handler_deletes_message_with_token(connection, mirror_env):
    from app.features.mirror.bot import on_token_received

    deleted, answers = [], []

    async def delete():
        deleted.append(1)

    async def answer(text, **kw):
        answers.append(text)

    class State:
        async def clear(self): ...

    msg = types_ns(
        from_user=types_ns(id=42), text=GOOD_TOKEN, delete=delete, answer=answer
    )
    await on_token_received(msg, State())
    assert deleted == [1] and answers


async def test_main_webhook_does_not_drop_pending_updates(monkeypatch):
    """Старт приложения ставит вебхук без сброса очереди (деплой не теряет архив)."""
    import app.main as app_module
    from config import settings

    calls = []

    class _Bot:
        async def set_webhook(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(app_module, "bot", _Bot())
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "https://example.test")
    await app_module._set_webhook()
    assert calls and not calls[0].get("drop_pending_updates")
    assert calls[0]["url"] == "https://example.test/webhook"


# --- 6/9. уведомление о правке: обрезка и вынос в поток ---------------------------
async def test_classic_edit_notice_is_clipped_below_telegram_limit(connection):
    from app.features.archive.bot.edited import notify_edited as _notify_edited
    from app.features.archive.prefs import defaults

    prefs = defaults()
    prefs = (
        prefs.__class__(**{**prefs.__dict__, "rich": False})
        if hasattr(prefs, "__dict__")
        else prefs
    )
    bot = FakeBot()
    msg = make_message("new", chat_id=7, from_id=7)
    old = {"text": "а" * 4096, "kind": "text"}
    new = {"text": "б" * 4096, "kind": "text"}
    await _notify_edited(
        bot, connection, msg, "ru", "Аня", "text", old, None, new, prefs=prefs
    )
    sent = bot.sent[-1]["text"]
    import re

    visible = re.sub(r"<[^>]+>", "", sent)
    assert len(visible) <= 4096


async def test_highlight_changes_async_matches_sync():
    from app.features.archive.render.classic import (
        highlight_changes,
        highlight_changes_async,
    )

    assert await highlight_changes_async("abc", "abXc") == highlight_changes(
        "abc", "abXc"
    )


# --- 8. гонки в играх -------------------------------------------------------------
async def test_serialized_game_runs_taps_one_by_one():
    import asyncio
    import gc
    import inspect

    from app.features.games import lock as game_lock
    from app.features.games.lock import serialized_game

    log = []

    @serialized_game
    async def handler(call, bot):
        log.append(("in", call.n))
        await asyncio.sleep(0.01)
        log.append(("out", call.n))

    def call(n, chat=7):
        return types_ns(
            n=n, message=types_ns(business_connection_id="c", chat=types_ns(id=chat))
        )

    assert list(inspect.signature(handler).parameters) == ["call", "bot"]  # aiogram DI
    await asyncio.gather(handler(call(1), None), handler(call(2), None))
    assert log == [("in", 1), ("out", 1), ("in", 2), ("out", 2)]

    # другой чат не ждёт; замки не копятся
    log.clear()
    await asyncio.gather(handler(call(1), None), handler(call(2, chat=8), None))
    assert [e for e, _ in log[:2]] == ["in", "in"]
    gc.collect()
    assert len(game_lock._locks) == 0


async def test_rapid_ttt_taps_do_not_lose_a_move(connection):
    """Два одновременных нажатия: оба хода применяются (раньше второй затирал первый)."""
    import asyncio

    from app.features.games.bot import ttt

    calls = []

    @ttt.serialized_game
    async def fake_move(call):
        game = await get_game("ttt", "conn-1", 7)
        board = list(game["board"] if game else "." * 9)
        await asyncio.sleep(0)  # точка переключения, где раньше терялся ход
        board[call.idx] = "X"
        await save_game("ttt", "conn-1", 7, board="".join(board), status="active")
        calls.append(call.idx)

    def call(i):
        return types_ns(
            idx=i,
            message=types_ns(business_connection_id="conn-1", chat=types_ns(id=7)),
        )

    await asyncio.gather(fake_move(call(0)), fake_move(call(1)))
    assert (await get_game("ttt", "conn-1", 7))["board"].count("X") == 2


# --- 7. spawn(): сильная ссылка и логирование падений -------------------------------
async def test_spawn_keeps_reference_and_logs_failure(caplog):
    import asyncio

    from app.platform import tasks

    async def boom():
        raise ValueError("kaboom")

    task = tasks.spawn(boom(), name="boom")
    assert task in tasks._tasks  # ссылка удерживается
    await asyncio.sleep(0.01)
    assert task not in tasks._tasks
    assert any("boom" in r.getMessage() for r in caplog.records)
