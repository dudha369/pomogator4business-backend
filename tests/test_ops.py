"""Наблюдаемость (задача 35): журнал ошибок, scrub, оповещения, проверка старта."""

import asyncio
import logging
import types

import pytest
from fastapi.testclient import TestClient
from tortoise import Tortoise

from app.features.ops import health, notify, scrub, service, sink, startup
from app.features.ops.models import ErrorEvent
from app.platform import log_context
from app.platform.logging_config import SecretsFormatter, redact_secrets
from config import settings
from tests.conftest import FakeBot

SECRET_TEXT = "СЕКРЕТНЫЙ_ТЕКСТ_ПЕРЕПИСКИ_777"
ADMIN = 4242


@pytest.fixture
def ops_bot(monkeypatch):
    """Администратор в ADMIN_USER_IDS, а основной бот — FakeBot."""
    bot = FakeBot()
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", str(ADMIN))
    monkeypatch.setattr(notify, "_bot", lambda: bot)
    service.throttle = service.Throttle()
    sink.drain()
    sink.install()
    health.clear_cache()
    yield bot
    sink.uninstall()
    sink.drain()


def boom(text: str = SECRET_TEXT):
    raise ValueError(f"плохой ввод: {text}")


def caught(fn=boom, *args) -> BaseException:
    try:
        fn(*args)
    except Exception as exc:
        return exc
    raise AssertionError("не упало")


# --- scrub и отпечаток -------------------------------------------------------------


def test_sample_has_no_exception_text_for_unknown_types():
    d = scrub.describe(caught())
    assert SECRET_TEXT not in d.sample
    assert "ValueError (текст скрыт)" in d.sample
    assert "tests/test_ops.py" in d.sample and "boom" in d.sample


def test_known_safe_types_keep_redacted_message():
    from aiogram.exceptions import TelegramBadRequest

    exc = TelegramBadRequest(
        method=None, message=f"Bad Request: key=abc123 {'x' * 200}"
    )
    d = scrub.describe(exc)
    assert "key=<hidden>" in d.sample and "abc123" not in d.sample
    assert len(d.sample) < scrub.MAX_SAMPLE + 10


def test_tokens_urls_and_blobs_are_redacted():
    text = (
        f"{settings.BOT_TOKEN} 123456789:AAH{'a' * 33} tg://login?token=zzz "
        f"https://x.io/p?api_key=1&b=2 {'Q' * 60}"
    )
    out = scrub.scrub_text(text)
    for leak in (settings.BOT_TOKEN, "AAH", "zzz", "api_key=1", "Q" * 60):
        assert leak not in out


def test_fingerprint_stable_between_lines_and_distinct_by_function():
    a = scrub.describe(caught())
    b = scrub.describe(caught())
    assert a.fingerprint_key == b.fingerprint_key  # файл:функция, не строка
    assert ":" in a.place and " boom" in a.place  # для людей: файл:строка функция

    def other():
        raise ValueError("x")

    c = scrub.describe(caught(other))
    assert c.fingerprint_key != a.fingerprint_key


def test_critical_kinds_detected():
    from app.features.vault.service import VaultError

    assert scrub.describe(
        caught(lambda: (_ for _ in ()).throw(VaultError("k")))
    ).critical
    assert not scrub.describe(caught()).critical


# --- логи --------------------------------------------------------------------------


def test_log_formatter_hides_secrets_but_keeps_everything_else():
    fmt = SecretsFormatter("%(message)s")
    rec = logging.LogRecord(
        "x",
        logging.ERROR,
        "f",
        1,
        f"url https://a.b/?token=zz {settings.BOT_TOKEN} ok",
        (),
        None,
    )
    out = fmt.format(rec)
    assert "zz" not in out and settings.BOT_TOKEN not in out and "ok" in out
    assert redact_secrets("обычный текст 12345") == "обычный текст 12345"


def test_log_context_rendered_in_line():
    log_context.reset()
    log_context.bind(upd=7, owner=42, comp="bot", step="record_history")
    rec = logging.LogRecord("x", logging.INFO, "f", 1, "msg", (), None)
    assert log_context.ContextFilter().filter(rec)
    assert rec.ctx == "[upd=7 owner=42 comp=bot step=record_history] "


# --- приёмник и журнал -------------------------------------------------------------


async def test_handler_collects_and_groups_repeats(database, ops_bot):
    log = logging.getLogger("bot.something")
    for _ in range(3):
        log.error("сбой", exc_info=caught())
    log.warning("подавлено", exc_info=caught())  # WARNING — не ошибка
    await sink.flush_once(now=1000)
    rows = await ErrorEvent.all()
    assert len(rows) == 1 and rows[0].count == 3
    assert SECRET_TEXT not in rows[0].sample and SECRET_TEXT not in rows[0].place


async def test_same_exception_logged_twice_counts_once(database, ops_bot):
    exc = caught()
    logging.getLogger("bot.updates").error("✗ апдейт", exc_info=exc)
    logging.getLogger("bot.webhook").error("не удалось", exc_info=exc)
    await sink.flush_once(now=1000)
    assert (await ErrorEvent.get()).count == 1


async def test_own_logger_is_ignored(database, ops_bot):
    logging.getLogger("bot.ops").error("внутреннее", exc_info=caught())
    assert sink.drain() == []


async def test_component_from_context(database, ops_bot):
    log_context.reset()
    log_context.bind(comp="mirror")
    logging.getLogger("bot.x").error("e", exc_info=caught())
    await sink.flush_once(now=1000)
    assert (await ErrorEvent.get()).component == "mirror"


async def test_message_content_never_reaches_journal_or_alert(database, ops_bot):
    logging.getLogger("bot.x").error("e", exc_info=caught())
    await sink.flush_once(now=1000)
    everything = " ".join(m["text"] for m in ops_bot.sent)
    everything += " ".join(
        str(v) for r in await ErrorEvent.all().values() for v in r.values()
    )
    assert SECRET_TEXT not in everything


# --- оповещения --------------------------------------------------------------------


async def test_new_error_alerts_admin_with_buttons(database, ops_bot):
    logging.getLogger("bot.x").error("e", exc_info=caught())
    await sink.flush_once(now=1000)
    assert len(ops_bot.sent) == 1
    msg = ops_bot.sent[0]
    assert msg["chat_id"] == ADMIN and "Новая ошибка" in msg["text"]
    data = [b.callback_data for row in msg["reply_markup"].inline_keyboard for b in row]
    assert {d.split(":")[1] for d in data} == {"ok", "mute", "info"}
    assert not ops_bot.html_problems


def test_decide_rules():
    base = {
        "critical": False,
        "count": 5,
        "notified_count": 1,
        "notified_at": 0,
        "acked_at": None,
        "muted_until": None,
        "now": 4000,
        "repeat_seconds": 3600,
    }
    assert service.decide(**{**base, "notified_at": None}) == "new"
    assert service.decide(**base) == "repeat"
    assert service.decide(**{**base, "now": 100}) is None  # рано
    assert service.decide(**{**base, "count": 1}) is None  # нет новых
    assert service.decide(**{**base, "muted_until": 9999}) is None
    assert service.decide(**{**base, "acked_at": 3000}) is None
    # критичная: не глушится, но не чаще 10 минут
    crit = {**base, "critical": True, "muted_until": 9999, "acked_at": 3999}
    assert service.decide(**{**crit, "now": 700}) == "repeat"
    assert service.decide(**{**crit, "now": 300}) is None


async def test_repeat_once_per_hour_with_counter(database, ops_bot):
    log = logging.getLogger("bot.x")
    log.error("e", exc_info=caught())
    await sink.flush_once(now=1000)
    log.error("e", exc_info=caught())
    await sink.flush_once(now=1500)  # рано
    assert len(ops_bot.sent) == 1
    log.error("e", exc_info=caught())
    await sink.flush_once(now=1000 + 3600)
    assert len(ops_bot.sent) == 2 and "Ошибка повторяется" in ops_bot.sent[1]["text"]
    assert "ещё 2" in ops_bot.sent[1]["text"]


async def test_burst_message_and_pause(database, ops_bot, monkeypatch):
    monkeypatch.setattr(settings, "OPS_BURST_THRESHOLD", 5)
    for i in range(6):
        # разные функции — разные отпечатки
        ns = {}
        exec(f"def g{i}():\n    raise KeyError({i})", ns)
        logging.getLogger("bot.x").error("e", exc_info=caught(ns[f"g{i}"]))
    await sink.flush_once(now=1000)
    texts = [m["text"] for m in ops_bot.sent]
    assert any("Всплеск ошибок" in t for t in texts)
    assert not any("Новая ошибка" in t for t in texts)  # обычные приостановлены


async def test_hourly_cap_counts_hidden(database, ops_bot, monkeypatch):
    monkeypatch.setattr(settings, "OPS_MAX_PER_HOUR", 1)
    for i in range(2):
        ns = {}
        exec(f"def h{i}():\n    raise KeyError({i})", ns)
        logging.getLogger("bot.x").error("e", exc_info=caught(ns[f"h{i}"]))
    await sink.flush_once(now=1000)
    assert len(ops_bot.sent) == 1
    assert service.throttle.hidden == 1


async def test_critical_bypasses_cap_and_mute(database, ops_bot, monkeypatch):
    from app.features.vault.service import VaultError

    monkeypatch.setattr(settings, "OPS_MAX_PER_HOUR", 0)
    logging.getLogger("bot.vault").error(
        "e", exc_info=caught(lambda: (_ for _ in ()).throw(VaultError("k")))
    )
    await sink.flush_once(now=1000)
    assert len(ops_bot.sent) == 1 and "Критичная" in ops_bot.sent[0]["text"]


async def test_db_failure_requeues_and_notifies_once(database, ops_bot, monkeypatch):
    async def broken(items, now):
        raise RuntimeError("db down")

    monkeypatch.setattr(service, "process", broken)
    monkeypatch.setattr(sink, "_last_db_notice", 0.0)
    logging.getLogger("bot.x").error("e", exc_info=caught())
    assert await sink.flush_once(now=1000) == 0
    assert any("База данных недоступна" in m["text"] for m in ops_bot.sent)
    assert len(sink._pending) == 1  # событие не потеряно


# --- кнопки ------------------------------------------------------------------------


def _cq(user_id, data):
    answers, edits = [], []

    async def answer(text=None, show_alert=False):
        answers.append(text)

    async def edit_text(text, **kw):
        edits.append(text)

    msg = types.SimpleNamespace(edit_text=edit_text)
    cq = types.SimpleNamespace(
        from_user=types.SimpleNamespace(id=user_id),
        data=data,
        message=msg,
        answer=answer,
    )
    return cq, answers, edits


async def test_buttons_check_admin_every_time(database, ops_bot):
    from app.features.ops.bot import on_button

    row = await ErrorEvent.create(
        fingerprint="f" * 40,
        component="bot",
        kind="K",
        place="a.py:1 f",
        first_at=1,
        last_at=1,
        sample="S",
    )
    cq, answers, _ = _cq(111, f"ops:ok:{row.id}")  # не админ
    await on_button(cq)
    assert answers == ["Нет доступа"]
    assert (await ErrorEvent.get(id=row.id)).acked_at is None

    cq, _, _ = _cq(ADMIN, f"ops:ok:{row.id}")
    await on_button(cq)
    assert (await ErrorEvent.get(id=row.id)).acked_at

    cq, _, _ = _cq(ADMIN, f"ops:mute:{row.id}")
    await on_button(cq)
    assert (await ErrorEvent.get(id=row.id)).muted_until

    cq, _, edits = _cq(ADMIN, f"ops:info:{row.id}")
    await on_button(cq)
    assert "<pre>S</pre>" in edits[0]


# --- проверка старта ---------------------------------------------------------------


async def _set_aerich(version):
    conn = Tortoise.get_connection("default")
    await conn.execute_script(
        'CREATE TABLE IF NOT EXISTS "aerich" (id INTEGER PRIMARY KEY, version VARCHAR(255), '
        "app VARCHAR(100), content TEXT)"
    )
    await conn.execute_script('DELETE FROM "aerich"')
    if version:
        await conn.execute_query(
            "INSERT INTO aerich (id, version, app, content) VALUES (1, ?, 'models', '{}')"
            if "sqlite" in settings.DB_URL
            else "INSERT INTO aerich (id, version, app, content) VALUES (1, $1, 'models', '{}')",
            [version],
        )


def test_repo_version_is_last_migration_file():
    assert startup.repo_version() >= 25


async def test_migration_equal_passes(database):
    await _set_aerich(f"{startup.repo_version()}_20261126000000_x.py")
    await startup.check_migrations()


@pytest.mark.parametrize("delta", [-1, 1])
async def test_migration_mismatch_refuses_both_directions(database, delta):
    await _set_aerich(f"{startup.repo_version() + delta}_20261126000000_x.py")
    with pytest.raises(startup.MigrationMismatch):
        await startup.check_migrations()


async def test_no_aerich_table_is_mismatch(database):
    with pytest.raises(startup.MigrationMismatch) as info:
        await startup.check_migrations()
    assert info.value.db is None


async def test_skip_flag_disables_check_only_when_set(database, monkeypatch):
    monkeypatch.setattr(settings, "SKIP_MIGRATION_CHECK", True)
    await startup.check_migrations()


async def test_failure_is_announced_to_admin(database, ops_bot):
    await startup.announce_failure(startup.MigrationMismatch(24, 25))
    text = ops_bot.sent[0]["text"]
    assert ops_bot.sent[0]["chat_id"] == ADMIN
    assert "24" in text and "25" in text and "aerich upgrade" in text


async def test_failure_text_has_no_dsn(database, ops_bot):
    await startup.announce_failure(
        RuntimeError(f"connect {settings.DB_URL} failed"), stage="db"
    )
    assert settings.DB_URL not in ops_bot.sent[0]["text"]


async def test_vault_failure_announced(database, ops_bot):
    from app.features.vault.service import VaultError

    await startup.announce_failure(
        VaultError("нет мастер-ключа версии 2"), stage="vault"
    )
    assert "нет мастер-ключа версии 2" in ops_bot.sent[0]["text"]


async def test_started_report_silent_when_green(database, ops_bot, monkeypatch):
    await _set_aerich(f"{startup.repo_version()}_x.py")
    monkeypatch.setattr(settings, "WEBHOOK_BASE_URL", "")
    monkeypatch.setattr(settings, "ADMIN_USER_IDS", str(ADMIN))
    await startup.report_started(delay=0)
    msg = ops_bot.sent[0]
    assert "Запущена сборка" in msg["text"] and "✓ БД" in msg["text"]


# --- /health/deep и /status --------------------------------------------------------


async def test_collect_reports_failed_migration(database, ops_bot):
    report = await health.collect(deep=True)
    assert report.status == "fail"
    assert {c.name: c.status for c in report.checks}["migrations"] == "fail"
    assert report.errors is not None and report.env["BOT_TOKEN"] is True


def test_health_deep_requires_secret_or_admin(monkeypatch):
    from app.main import app

    monkeypatch.setattr(settings, "HEALTH_SECRET", "s3cret-value")
    client = TestClient(app)
    assert client.get("/health/deep").status_code == 403
    assert (
        client.get("/health/deep", headers={"X-Health-Secret": "wrong"}).status_code
        == 403
    )
    assert client.get("/health").json() == {"status": "ok"}  # лёгкий остаётся лёгким


def test_request_id_header_and_500_body():
    """Отдельное приложение с теми же middleware и обработчиком: глобальный `app`
    (его схему сверяют другие тесты) не трогаем."""
    from fastapi import FastAPI

    from app.features.ops.middleware import RequestContextMiddleware
    from app.main import app as real_app
    from app.main import unhandled_error

    mini = FastAPI()
    mini.add_middleware(RequestContextMiddleware)
    mini.exception_handler(Exception)(unhandled_error)

    @mini.get("/_boom")
    async def _boom():
        raise RuntimeError(SECRET_TEXT)

    client = TestClient(mini, raise_server_exceptions=False)
    res = client.get("/_boom")
    assert res.status_code == 500
    body = res.json()
    assert body["code"] == "internal_error"
    assert body["request_id"] == res.headers["x-request-id"]
    assert SECRET_TEXT not in res.text
    # и на настоящем приложении заголовок есть
    assert TestClient(real_app).get("/health").headers["x-request-id"]


async def test_status_command_only_for_admin(database, ops_bot, monkeypatch):
    from app.features.ops.bot import _is_admin

    assert _is_admin(types.SimpleNamespace(id=ADMIN))
    assert not _is_admin(types.SimpleNamespace(id=1))
    assert not _is_admin(None)


async def test_retention_purges_old_events(database):
    from app.features.ops.retention import purge_error_events

    await ErrorEvent.create(
        fingerprint="a" * 40,
        component="bot",
        kind="K",
        place="p",
        first_at=1,
        last_at=1,
    )
    await ErrorEvent.create(
        fingerprint="b" * 40,
        component="bot",
        kind="K",
        place="p",
        first_at=10**10,
        last_at=10**10,
    )
    assert await purge_error_events(now=10**9) == 1
    assert await ErrorEvent.all().count() == 1


async def test_background_task_failure_goes_to_journal(database, ops_bot):
    from app.platform.tasks import spawn

    async def dies():
        raise KeyError("x")

    spawn(dies(), name="dies")
    await asyncio.sleep(0.05)
    await sink.flush_once(now=1000)
    assert (await ErrorEvent.get()).kind == "KeyError"


# --- сквозные ----------------------------------------------------------------------


async def test_webhook_failure_logs_no_message_text(database, caplog, monkeypatch):
    """Раньше при сбое в лог Render уходил ВЕСЬ апдейт, то есть текст переписки."""
    import hmac as _hmac  # noqa: F401

    from app import main

    async def failing(bot, data):
        raise ValueError("упало")

    monkeypatch.setattr(main.dp, "feed_webhook_update", failing)
    request = types.SimpleNamespace(
        json=lambda: _async({"update_id": 99, "message": {"text": SECRET_TEXT}})
    )
    with caplog.at_level(logging.INFO):
        res = await main.telegram_webhook(request, settings.WEBHOOK_SECRET)
    assert res.status_code == 200
    assert SECRET_TEXT not in caplog.text
    assert "апдейт 99" in caplog.text


async def _async(value):
    return value


async def test_aiogram_failure_end_to_end(database, ops_bot, caplog):
    """Настоящий Dispatcher: ошибка хендлера попадает в журнал один раз, контекст в логе."""
    from aiogram import Bot, Dispatcher, Router
    from aiogram.types import Chat, Message, Update, User

    from app.features.ops.middleware import OpsContextMiddleware
    from app.platform.logging_config import configure_logging
    from app.platform.telegram.middleware import UpdateLoggingMiddleware

    router = Router()

    @router.message()
    async def handler(message):
        raise KeyError("x")

    dp = Dispatcher()
    dp.update.outer_middleware(OpsContextMiddleware("bot"))
    dp.update.outer_middleware(UpdateLoggingMiddleware())
    dp.include_router(router)
    update = Update(
        update_id=555,
        message=Message(
            message_id=1,
            date=1,
            chat=Chat(id=7, type="private"),
            from_user=User(id=7, is_bot=False, first_name="x"),
            text=SECRET_TEXT,
        ),
    )
    configure_logging()
    sink.install()
    with caplog.at_level(logging.INFO), pytest.raises(KeyError):
        await dp.feed_update(Bot("1:T"), update)
    await sink.flush_once(now=1000)
    row = await ErrorEvent.get()
    assert row.component == "bot" and row.count == 1 and row.kind == "KeyError"
    assert SECRET_TEXT not in caplog.text


async def test_pipeline_step_name_bound_to_context():
    from app.platform.telegram.pipeline import _named

    async def record_history(handler, message, data):
        return log_context.current().get("step")

    log_context.reset()
    assert await _named(record_history)(None, None, {}) == "record_history"


async def test_health_deep_with_secret(database, ops_bot, monkeypatch):
    from app.features.ops.health_api import health_deep

    monkeypatch.setattr(settings, "HEALTH_SECRET", "s3cret-value")
    report = await health_deep(
        x_health_secret="s3cret-value", x_telegram_init_data=None
    )
    assert report.build and report.env["BOT_TOKEN"]
    dumped = report.model_dump_json()
    assert "s3cret-value" not in dumped and settings.BOT_TOKEN not in dumped


# --- scripts/smoke.py --------------------------------------------------------------


def test_smoke_init_data_is_valid_for_the_server():
    import json as _json

    from app.platform.telegram.auth import validate_init_data
    from scripts.smoke import make_init_data

    parsed = validate_init_data(
        make_init_data(settings.BOT_TOKEN, ADMIN), settings.BOT_TOKEN
    )
    assert _json.loads(parsed["user"])["id"] == ADMIN


def test_smoke_picks_only_safe_get_endpoints():
    from app.main import app
    from scripts.smoke import pick_endpoints

    paths = pick_endpoints(app.openapi())
    assert "/api/home" in paths
    assert not any("{" in p or "export" in p or "avatar" in p for p in paths)


async def test_smoke_vault_counts_failures_without_alerts(database, monkeypatch):
    import time as _time

    from app.features.ai.models import AiDraft
    from app.features.alerts.models import Alert
    from app.features.vault import service as vault
    from scripts.smoke import check_vault
    from tests.conftest import TEST_MASTER_KEYS

    vault.configure(TEST_MASTER_KEYS)
    sealed = await vault.seal_values("ai_drafts", ADMIN, {"text": "привет"})
    await AiDraft.create(
        owner_id=ADMIN,
        chat_id=1,
        source_message_id=1,
        created_at=int(_time.time()),
        **sealed,
    )
    assert await check_vault(10) == ([], 1)

    # ломаем шифротекст: проблема найдена, владельцу alert НЕ уходит
    await AiDraft.all().update(text="AAAA")
    problems, checked = await check_vault(10)
    assert checked == 1 and "ai_drafts" in problems[0]
    assert await Alert.all().count() == 0
    assert not vault.failed_owners


def test_ops_logic_modules_do_not_import_aiogram():
    from pathlib import Path

    base = Path(__file__).resolve().parent.parent / "app" / "features" / "ops"
    for name in ("service.py", "scrub.py", "models.py", "state.py"):
        text = (base / name).read_text(encoding="utf-8")
        assert "import aiogram" not in text and "from aiogram" not in text, name
