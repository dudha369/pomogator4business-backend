"""Лимиты и тарифы (задача 22): планы, единая проверка, предупреждение, подключения."""

import asyncio
import importlib
import time
from pathlib import Path

import pytest

from app.features.alerts.models import Alert
from app.features.limits import plans, queries, service
from app.features.limits.bot import enforce
from app.features.limits.models import UsageCounter
from app.features.limits.service import Allowed, Denied
from app.features.mirror import setup as mirror_setup
from app.features.mirror.models import MirrorBot
from app.platform.i18n import LOCALES
from app.platform.ttl_cache import clear_all
from config import settings

from .conftest import NOW, OWNER_ID, make_message, on_business_message
from .test_linkscan import PHISH, Fake, doc, drain, ent, incoming

DAY = 86400


@pytest.fixture(autouse=True)
def fresh_reports(monkeypatch):
    """Память «окно уже объявлено» живёт в процессе: каждому тесту — чистая."""
    monkeypatch.setattr("app.features.limits.bot._reported", set())


@pytest.fixture
def cfg(monkeypatch):
    """Подмена лимитов и админов: кэш плана сбрасывается сразу."""

    def apply(**values):
        for name, value in values.items():
            monkeypatch.setattr(settings, name, value)
        clear_all()

    return apply


# --- планы и значения ------------------------------------------------------------------
def test_free_defaults_keep_current_features_working():
    assert plans.limit_for("free", "mirrors") == 1  # зеркало и так одно на владельца
    assert plans.limit_for("free", "linkscan_checks_day") == 50
    assert plans.limit_for("free", "archive_groups") == 3
    assert plans.limit_for("free", "stored_messages") is None  # нет лимита
    assert plans.limit_for("pro", "linkscan_checks_day") is None


def test_env_overrides_defaults_and_minus_one_means_unlimited(cfg, caplog):
    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=5, mirrors=-1, bogus=3, archive_groups=x")
    assert plans.limit_for("free", "linkscan_checks_day") == 5
    assert plans.limit_for("free", "mirrors") is None
    assert plans.limit_for("free", "archive_groups") == 3  # битое значение пропущено
    assert "bogus" in caplog.text and "archive_groups=x" in caplog.text


def test_admin_unknown_plan_and_typo():
    assert plans.limit_for(plans.ADMIN, "mirrors") is None
    assert plans.limit_for("legacy-plan", "mirrors") == 1  # неизвестный план — free
    with pytest.raises(KeyError):
        plans.limit_for("free", "mirrorz")


def test_window_period_is_utc_day():
    assert plans.period_start("linkscan_checks_day", NOW) == NOW - NOW % DAY
    assert plans.period_start("mirrors", NOW) is None


# --- тариф владельца ---------------------------------------------------------------------
async def test_plan_defaults_to_free_and_follows_table(database):
    assert (await service.plan_of(OWNER_ID))["plan"] == "free"
    await queries.set_plan(OWNER_ID, "pro", "payment")
    assert await service.plan_of(OWNER_ID) == {
        "plan": "pro",
        "source": "payment",
        "expires_at": None,
    }


async def test_expired_plan_falls_back_to_free_without_deleting(database):
    await queries.set_plan(OWNER_ID, "pro", "payment", int(time.time()) - 10)
    assert (await service.plan_of(OWNER_ID))["plan"] == "free"
    assert (await queries.get_plan(OWNER_ID))["plan"] == "pro"  # строка цела
    await queries.set_plan(OWNER_ID, "pro", "payment", int(time.time()) + 600)
    assert (await service.plan_of(OWNER_ID))["plan"] == "pro"


async def test_admin_wins_over_any_row(database, cfg):
    await queries.set_plan(OWNER_ID, "free", "free")
    cfg(ADMIN_USER_IDS=f" 1, {OWNER_ID},x")
    assert await service.plan_of(OWNER_ID) == {
        "plan": "admin",
        "source": "admin",
        "expires_at": None,
    }
    assert isinstance(await service.check(OWNER_ID, "linkscan_checks_day"), Allowed)


# --- check: состояние ----------------------------------------------------------------------
async def test_state_metric_compares_current_plus_need(database):
    assert isinstance(
        await service.check(OWNER_ID, "archive_groups", current=2), Allowed
    )
    denied = await service.check(OWNER_ID, "archive_groups", need=1, current=3)
    assert denied == Denied("archive_groups", 3, 3, "free", None)
    assert isinstance(
        await service.check(OWNER_ID, "archive_groups", need=2, current=2), Denied
    )


async def test_state_metric_needs_current_and_zero_forbids(database, cfg):
    with pytest.raises(ValueError):
        await service.check(OWNER_ID, "archive_groups")
    cfg(PLAN_LIMITS_FREE="mirrors=0")
    assert isinstance(await service.check(OWNER_ID, "mirrors", current=0), Denied)


async def test_value_metric_is_not_a_counter(database):
    with pytest.raises(ValueError):
        await service.check(OWNER_ID, "retention_days", current=1)
    with pytest.raises(KeyError):
        await service.check(OWNER_ID, "typo", current=1)


# --- check: окно -----------------------------------------------------------------------------
async def test_window_counts_until_limit_then_denies(database, cfg):
    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=3")
    results = [
        await service.check(OWNER_ID, "linkscan_checks_day", now=NOW) for _ in range(4)
    ]
    assert [isinstance(r, Allowed) for r in results] == [True, True, True, False]
    assert results[3] == Denied("linkscan_checks_day", 3, 3, "free", NOW - NOW % DAY)
    # отказ ничего не прибавляет
    assert (await UsageCounter.get(owner_id=OWNER_ID)).value == 3


async def test_window_resets_next_utc_day(database, cfg):
    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=1")
    assert isinstance(
        await service.check(OWNER_ID, "linkscan_checks_day", now=NOW), Allowed
    )
    assert isinstance(
        await service.check(OWNER_ID, "linkscan_checks_day", now=NOW), Denied
    )
    tomorrow = NOW + DAY
    assert isinstance(
        await service.check(OWNER_ID, "linkscan_checks_day", now=tomorrow), Allowed
    )
    assert await UsageCounter.filter(owner_id=OWNER_ID).count() == 2


async def test_window_need_larger_than_limit_is_denied(database, cfg):
    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=2")
    assert isinstance(
        await service.check(OWNER_ID, "linkscan_checks_day", need=3, now=NOW), Denied
    )
    assert await UsageCounter.all().count() == 0


async def test_unlimited_plan_writes_no_counters(database):
    await queries.set_plan(OWNER_ID, "pro", "promo")
    for _ in range(3):
        assert isinstance(await service.check(OWNER_ID, "linkscan_checks_day"), Allowed)
    assert await UsageCounter.all().count() == 0


async def test_parallel_checks_never_exceed_limit(database, cfg):
    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=5")
    results = await asyncio.gather(
        *(service.check(OWNER_ID, "linkscan_checks_day", now=NOW) for _ in range(20))
    )
    assert sum(isinstance(r, Allowed) for r in results) == 5
    assert (await UsageCounter.get(owner_id=OWNER_ID)).value == 5


# --- предупреждение --------------------------------------------------------------------------
async def test_enforce_allows_silently(database, alerts_bot):
    assert await enforce(OWNER_ID, "archive_groups", current=0)
    assert alerts_bot.sent == [] and await Alert.all().count() == 0


async def test_enforce_denial_alerts_once_and_keeps_data(database, cfg, alerts_bot):
    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=1")
    assert await enforce(OWNER_ID, "linkscan_checks_day")
    assert not await enforce(OWNER_ID, "linkscan_checks_day")
    assert not await enforce(OWNER_ID, "linkscan_checks_day")
    (sent,) = alerts_bot.sent  # одно сообщение, повторы молчат
    assert "Лимит тарифа" in sent["text"] and "в сутки" in sent["text"]
    assert "тарифе «free»" in sent["text"] and "(1)" in sent["text"]
    assert await Alert.filter(
        owner_id=OWNER_ID, code="limit_reached:linkscan_checks_day"
    ).exists()
    assert (await UsageCounter.get(owner_id=OWNER_ID)).value == 1  # данные не тронуты


async def test_muted_limit_alert_stays_silent(database, cfg, alerts_bot):
    cfg(PLAN_LIMITS_FREE="archive_groups=0")
    assert not await enforce(OWNER_ID, "archive_groups", current=0)
    alert = await Alert.get(owner_id=OWNER_ID, code="limit_reached:archive_groups")
    from app.features.alerts import service as alerts

    await alerts.mute(OWNER_ID, alert.id)
    alerts_bot.sent.clear()
    assert not await enforce(OWNER_ID, "archive_groups", current=0)
    assert alerts_bot.sent == []


# --- зеркало ---------------------------------------------------------------------------------
class _Me:
    id, username = 5, "m_bot"


class _Bot:
    def __init__(self, token):
        pass

    async def get_me(self):
        return _Me

    class session:
        @staticmethod
        async def close():
            pass


@pytest.fixture
def mirror_started(monkeypatch):
    started = []

    async def start(*a, **k):
        started.append(a)

    monkeypatch.setattr(mirror_setup, "AiogramBot", _Bot)
    monkeypatch.setattr(mirror_setup.mirror_manager, "start_mirror", start)
    monkeypatch.setattr(mirror_setup, "encrypt_token", lambda t: b"x")
    return started


TOKEN = "123456:" + "A" * 35


async def test_mirror_connects_on_default_free_plan(database, mirror_started):
    assert await mirror_setup.connect_mirror(OWNER_ID, TOKEN) == "m_bot"
    # повторное подключение (замена токена) тоже проходит
    assert await mirror_setup.connect_mirror(OWNER_ID, TOKEN) == "m_bot"
    assert await MirrorBot.filter(owner_id=OWNER_ID).count() == 1


async def test_mirror_forbidden_by_plan_is_not_started_and_alerts(
    database, cfg, mirror_started, alerts_bot
):
    cfg(PLAN_LIMITS_FREE="mirrors=0")
    with pytest.raises(mirror_setup.MirrorSetupError) as exc:
        await mirror_setup.connect_mirror(OWNER_ID, TOKEN)
    assert exc.value.code == "limit_reached"
    assert mirror_started == [] and await MirrorBot.all().count() == 0
    assert await Alert.filter(owner_id=OWNER_ID, code="limit_reached:mirrors").exists()
    assert "Новое зеркало не подключено" in alerts_bot.sent[0]["text"]


async def test_mirror_limit_api_answers_403(client, cfg, mirror_started):
    cfg(PLAN_LIMITS_FREE="mirrors=0")
    resp = await client.post(
        "/api/mirror/connect", json={"token": TOKEN}, headers=client.owner
    )
    assert resp.status_code == 403 and resp.json()["detail"] == "limit_reached"


# --- Linkscan --------------------------------------------------------------------------------
@pytest.fixture
def provider(monkeypatch):
    from app.features.linkscan.verdict import Verdict

    fake = Fake("urlhaus", "cheap", Verdict())
    monkeypatch.setattr("app.features.linkscan.bot.PROVIDERS", (fake,))
    monkeypatch.setattr("app.features.linkscan.service.PROVIDERS", (fake,))
    return fake


def phish(host):
    return incoming(PHISH, [ent("text_link", 8, 10, f"https://{host}/login")])


async def test_linkscan_over_limit_skips_external_but_keeps_local_checks(
    connection, bot, cfg, alerts_bot, provider
):
    from app.features.linkscan import queries as linkscan

    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=1")
    await linkscan.update_settings(OWNER_ID, enabled=True)
    await on_business_message(phish("evil1.example"), bot)
    await on_business_message(phish("evil2.example"), bot)
    await drain()
    assert provider.calls == ["https://evil1.example/login"]  # второй не ушёл наружу
    codes = set(await Alert.filter(owner_id=OWNER_ID).values_list("code", flat=True))
    # локальная проверка сработала на обоих адресах + один alert про лимит
    assert codes == {
        "dangerous_link:evil1.example",
        "dangerous_link:evil2.example",
        "limit_reached:linkscan_checks_day",
    }


async def test_linkscan_over_limit_does_not_download_files(
    connection, bot, cfg, provider
):
    from app.features.linkscan import queries as linkscan

    cfg(PLAN_LIMITS_FREE="linkscan_checks_day=0")
    await linkscan.update_settings(OWNER_ID, enabled=True)
    await on_business_message(make_message(None, document=doc("a.pdf")), bot)
    await drain()
    assert provider.calls == []
    assert not any(c[0] == "get_file" for c in getattr(bot, "calls", []))


async def test_linkscan_without_external_services_spends_no_limit(
    connection, bot, provider
):
    from app.features.linkscan import queries as linkscan

    await linkscan.update_settings(OWNER_ID, enabled=True, external=False)
    await on_business_message(phish("evil1.example"), bot)
    await drain()
    assert provider.calls == [] and await UsageCounter.all().count() == 0


async def test_linkscan_trusted_hosts_do_not_spend_limit(connection, bot, provider):
    from app.features.linkscan import queries as linkscan

    await linkscan.update_settings(OWNER_ID, enabled=True)
    msg = incoming("t.me/x", [ent("url", 0, 6)])
    await on_business_message(msg, bot)
    await drain()
    assert provider.calls == [] and await UsageCounter.all().count() == 0


# --- API -------------------------------------------------------------------------------------
async def test_plan_endpoint_for_free_owner(client, database):
    await service.check(OWNER_ID, "linkscan_checks_day")
    await MirrorBot.create(
        owner_id=OWNER_ID,
        token_encrypted=b"x",
        bot_id=1,
        bot_username="m",
        created_at=1,
    )
    body = (await client.get("/api/plan", headers=client.owner)).json()
    assert body["plan"] == "free" and body["is_admin"] is False
    by_metric = {row["metric"]: row for row in body["limits"]}
    assert by_metric["linkscan_checks_day"] == {
        "metric": "linkscan_checks_day",
        "limit": 50,
        "used": 1,
        "period": "day",
    }
    assert by_metric["mirrors"]["used"] == 1 and by_metric["mirrors"]["limit"] == 1
    assert by_metric["archive_groups"]["used"] is None  # подключит 17.2
    assert by_metric["retention_days"]["period"] == "plan"
    assert set(by_metric) == set(plans.METRICS)


async def test_plan_endpoint_for_admin_is_unlimited(client, cfg):
    cfg(ADMIN_USER_IDS=str(OWNER_ID))
    body = (await client.get("/api/plan", headers=client.owner)).json()
    assert body["plan"] == "admin" and body["is_admin"] is True
    assert all(row["limit"] is None for row in body["limits"])


# --- очистка, слои, тексты -------------------------------------------------------------------
async def test_retention_purges_only_old_periods(database):
    from app.features.limits.retention import purge_counters

    await UsageCounter.create(
        owner_id=1, metric="m", period_start=NOW - 41 * DAY, value=1
    )
    await UsageCounter.create(owner_id=1, metric="m", period_start=NOW - DAY, value=1)
    assert await purge_counters(NOW) == 1
    assert await UsageCounter.all().count() == 1


def test_logic_layers_do_not_import_aiogram():
    for name in ("plans", "queries", "service", "models"):
        module = importlib.import_module(f"app.features.limits.{name}")
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "import aiogram" not in source and "from aiogram" not in source, name


def test_every_metric_has_texts_in_all_languages():
    for locale, words in LOCALES.items():
        for name, metric in plans.METRICS.items():
            assert f"limits.metric.{name}" in words, (locale, name)
            assert f"limits.effect.{metric.effect}" in words, (locale, name)
        assert "alert.limit_reached.title" in words
        assert "mirror.limit_reached" in words
