"""Linkscan: локальные проверки, лимиты, провайдеры, кэш, шаг конвейера, API."""

import asyncio
import importlib
import types
from pathlib import Path

import pytest

from app.features.alerts.models import Alert
from app.features.linkscan import providers as prov
from app.features.linkscan import queries, service
from app.features.linkscan.local import (
    assess_file,
    assess_link,
    entity_text,
    extract_links,
    make_link,
)
from app.features.linkscan.ratelimit import DailyBudget, TokenBucket
from app.features.linkscan.verdict import CLEAN, DANGER, NOTE, SUSPICIOUS, Verdict
from app.platform.i18n import LOCALES
from app.platform.tasks import _tasks
from config import settings

from .conftest import NOW, OWNER_ID, make_message, on_business_message


def ent(kind, offset, length, url=None):
    return types.SimpleNamespace(type=kind, offset=offset, length=length, url=url)


def link(display, url):
    result = make_link(display, url)
    assert result is not None
    return result


async def drain():
    while _tasks:
        await asyncio.gather(*list(_tasks))


# --- локальные проверки --------------------------------------------------------------
def test_entity_offsets_are_utf16():
    text = "😀 go example.com"  # эмодзи занимает 2 единицы UTF-16, а не 1
    assert entity_text(text, 6, 11) == "example.com"


def reasons(display, url):
    return set(assess_link(link(display, url)).reasons)


def test_mismatch_is_the_main_sign():
    verdict = assess_link(link("paypal.com", "https://evil.example/login"))
    assert verdict.level == SUSPICIOUS and "mismatch" in verdict.reasons


def test_same_site_and_plain_text_are_clean():
    assert reasons("example.com", "https://www.example.com/a") == set()
    assert reasons("docs.example.com", "https://example.com/") == set()
    assert reasons("Читать далее", "https://example.com/post") == set()
    assert reasons("https://example.com/a", "https://example.com/b") == set()


def test_userinfo_trick():
    assert "userinfo" in reasons("x", "https://paypal.com@evil.example/")


def test_lookalike_mixed_scripts_and_punycode_note():
    mixed = "https://p\u0430ypal.com/"  # кириллическая «а» среди латиницы
    assert assess_link(link("x", mixed)).level == SUSPICIOUS
    assert "lookalike" in reasons("x", mixed)
    only_idn = assess_link(link("x", "https://почта.рф/"))
    assert only_idn.level == NOTE and only_idn.reasons == ("punycode",)


def test_weak_signals_are_notes_only():
    assert assess_link(link("x", "https://bit.ly/abc")).level == NOTE
    assert reasons("x", "http://shop.example.top/") == {"bad_tld"}
    assert reasons("x", "http://203.0.113.5/a") == {"ip_host"}


def test_non_http_and_broken_urls_are_skipped():
    assert make_link("x", "javascript:alert(1)") is None
    assert make_link("x", "tg://resolve?domain=a") is None
    assert make_link("x", "http://[bad") is None
    assert make_link("x", "https://example.com/" + "a" * 3000) is None


def test_scheme_is_added_and_fragment_dropped():
    result = link("example.com/x", "example.com/x#frag")
    assert result.url == "http://example.com/x" and result.host == "example.com"


def test_extract_links_from_entities_dedupes_and_limits():
    text = "a.com b.com a.com click"
    entities = [
        ent("url", 0, 5),
        ent("url", 6, 5),
        ent("url", 12, 5),  # дубль
        ent("text_link", 18, 5, "https://c.example/"),
        ent("bold", 0, 5),
        ent("mention", 0, 1),
    ]
    found = extract_links(text, entities, limit=10)
    assert [x.host for x in found] == ["a.com", "b.com", "c.example"]
    assert len(extract_links(text, entities, limit=2)) == 2
    assert extract_links(None, entities, limit=5) == []


def test_assess_file():
    assert assess_file("photo.jpg").level == CLEAN
    assert assess_file(None).level == CLEAN
    assert assess_file("setup.exe").reasons == ("risky_file",)
    assert assess_file("scan.apk").level == NOTE
    double = assess_file("invoice.PDF.exe")
    assert double.level == SUSPICIOUS and double.reasons == ("double_extension",)
    assert assess_file("archive.tar.zip").level == NOTE  # не документ перед zip


# --- ограничители --------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def test_token_bucket_allows_four_per_minute():
    clock = Clock()
    bucket = TokenBucket(4, clock)
    assert [bucket.try_acquire() for _ in range(5)] == [True] * 4 + [False]
    clock.now += 15  # +1 токен
    assert bucket.try_acquire() and not bucket.try_acquire()


async def test_acquire_gives_up_when_wait_is_too_long():
    clock = Clock()
    bucket = TokenBucket(4, clock)
    for _ in range(4):
        bucket.try_acquire()
    assert await bucket.acquire(max_wait=1) is False


async def test_acquire_waits_for_free_slot(monkeypatch):
    clock = Clock()
    bucket = TokenBucket(4, clock)
    for _ in range(4):
        bucket.try_acquire()

    async def fake_sleep(seconds):
        clock.now += seconds

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    assert await bucket.acquire(max_wait=20) is True


def test_daily_budget_resets_next_utc_day_and_exhaust():
    clock = Clock()
    clock.now = 86400 * 10 + 5
    budget = DailyBudget(2, clock)
    assert [budget.take() for _ in range(3)] == [True, True, False]
    clock.now += 86400
    assert budget.take()
    budget.exhaust()
    assert not budget.take()
    clock.now += 86400
    assert budget.take()
    assert DailyBudget(0, clock).take()  # 0 — без лимита


# --- провайдеры ----------------------------------------------------------------------
@pytest.fixture
def http(monkeypatch):
    """Подмена сети: очередь ответов (status, body); вызовы записываются."""
    calls, answers = [], []

    async def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        return answers.pop(0) if answers else (0, None)

    monkeypatch.setattr(prov, "http_json", fake)
    fake.calls, fake.answers = calls, answers
    return types.SimpleNamespace(calls=calls, answers=answers)


async def test_urlhaus_url_and_payload(monkeypatch, http):
    monkeypatch.setattr(settings, "URLHAUS_AUTH_KEY", "k")
    provider = prov.URLhaus()
    assert provider.enabled()
    http.answers += [
        (200, {"query_status": "ok", "url_status": "online"}),
        (200, {"query_status": "ok", "url_status": "offline"}),
        (200, {"query_status": "no_results"}),
        (401, {"query_status": "unknown_auth_key"}),
        (200, {"query_status": "ok"}),
        (200, {"query_status": "no_results"}),
    ]
    assert (await provider.check_url("http://x/a")).level == DANGER
    assert (await provider.check_url("http://x/a")).level == SUSPICIOUS
    assert (await provider.check_url("http://x/a")).level == CLEAN
    assert await provider.check_url("http://x/a") is None
    assert (await provider.check_file("a" * 64)).reasons == ("malware",)
    assert (await provider.check_file("b" * 64)).level == CLEAN
    method, url, kwargs = http.calls[0]
    assert method == "POST" and url.endswith("/v1/url/")
    assert kwargs["headers"] == {"Auth-Key": "k"} and kwargs["data"] == {
        "url": "http://x/a"
    }
    assert http.calls[4][2]["data"] == {"sha256_hash": "a" * 64}


async def test_safe_browsing_match_empty_and_error(monkeypatch, http):
    monkeypatch.setattr(settings, "SAFE_BROWSING_API_KEY", "gk")
    provider = prov.SafeBrowsing()
    http.answers += [
        (
            200,
            {
                "matches": [
                    {"threatType": "SOCIAL_ENGINEERING", "cacheDuration": "300.000s"},
                    {"threatType": "MALWARE", "cacheDuration": "120s"},
                ]
            },
        ),
        (200, {}),
        (500, None),
    ]
    hit = await provider.check_url("http://x/")
    assert hit.level == DANGER and set(hit.reasons) == {"phishing", "malware"}
    assert hit.ttl == 120  # не дольше самого короткого cacheDuration
    assert (await provider.check_url("http://x/")).level == CLEAN
    assert await provider.check_url("http://x/") is None
    sent = http.calls[0][2]
    assert sent["params"] == {"key": "gk"}
    assert sent["json"]["threatInfo"]["threatEntries"] == [{"url": "http://x/"}]


def vt_report(malicious=0, suspicious=0, results=()):
    return (
        200,
        {
            "data": {
                "attributes": {
                    "last_analysis_stats": {
                        "malicious": malicious,
                        "suspicious": suspicious,
                        "harmless": 60,
                    },
                    "last_analysis_results": {
                        f"e{i}": {"result": r} for i, r in enumerate(results)
                    },
                }
            }
        },
    )


@pytest.fixture
def vt(monkeypatch):
    monkeypatch.setattr(settings, "VT_API_KEY", "vk")
    monkeypatch.setattr(settings, "LINKSCAN_VT_ENABLED", True)
    provider = prov.VirusTotal()
    provider.bucket = TokenBucket(1000)  # лимит 4/мин проверяет отдельный тест
    return provider


async def test_virustotal_thresholds(vt, http):
    http.answers += [
        vt_report(malicious=3),  # «3 из 91» — только подозрение
        vt_report(malicious=1),  # один детектор — не повод
        vt_report(malicious=5),
        vt_report(malicious=2, results=["phishing", "Phishing site"]),
        (404, None),
        (500, None),
    ]
    assert (await vt.check_url("http://x/")).level == SUSPICIOUS
    assert (await vt.check_url("http://x/")).level == CLEAN
    many = await vt.check_url("http://x/")
    assert many.level == DANGER and many.reasons == ("flagged",)
    phish = await vt.check_url("http://x/")
    assert phish.level == DANGER and phish.reasons == ("phishing",)
    unknown = await vt.check_url("http://x/")
    assert unknown.level == CLEAN and unknown.ttl == prov.NOT_FOUND_TTL
    assert await vt.check_url("http://x/") is None
    assert http.calls[0][1].endswith("/urls/aHR0cDovL3gv")  # base64url без «=»
    assert http.calls[0][2]["headers"] == {"x-apikey": "vk"}


async def test_virustotal_file_needs_five_detections(vt, http):
    http.answers += [
        vt_report(malicious=2),
        vt_report(malicious=3),
        vt_report(malicious=6),
    ]
    assert (
        await vt.check_file("a" * 64)
    ).level == CLEAN  # один-два детекта у файлов бывают ложными
    assert (await vt.check_file("a" * 64)).level == SUSPICIOUS
    verdict = await vt.check_file("a" * 64)
    assert verdict.level == DANGER and verdict.reasons == ("malware",)
    assert http.calls[0][1].endswith(f"/files/{'a' * 64}")


async def test_virustotal_respects_limits(vt, http):
    vt.bucket = TokenBucket(4)
    for _ in range(4):
        http.answers.append(vt_report())
    for _ in range(4):
        assert await vt.check_url("http://x/") is not None
    vt.bucket._tokens = 0  # 4 запроса в минуту исчерпаны, ждать долго
    monkeypatch_wait = prov.VT_MAX_WAIT
    prov.VT_MAX_WAIT = 0
    try:
        assert await vt.check_url("http://x/") is None
    finally:
        prov.VT_MAX_WAIT = monkeypatch_wait
    assert len(http.calls) == 4  # пятый запрос в сеть не ушёл


async def test_virustotal_429_blocks_until_tomorrow(vt, http):
    http.answers.append((429, None))
    assert await vt.check_url("http://x/") is None
    assert await vt.check_url("http://x/") is None
    assert len(http.calls) == 1


def test_providers_without_key_or_disabled_are_skipped(monkeypatch):
    monkeypatch.setattr(settings, "URLHAUS_AUTH_KEY", "")
    monkeypatch.setattr(settings, "SAFE_BROWSING_API_KEY", "")
    monkeypatch.setattr(settings, "VT_API_KEY", "")
    assert not any(p.enabled() for p in prov.PROVIDERS)
    monkeypatch.setattr(settings, "VT_API_KEY", "vk")
    monkeypatch.setattr(
        settings, "LINKSCAN_VT_ENABLED", False
    )  # для публичного сервиса
    assert not prov.VirusTotal().enabled()


async def test_http_error_is_logged_without_url(monkeypatch, caplog):
    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("https://x/?key=SECRET")

    monkeypatch.setattr(prov.aiohttp, "ClientSession", Boom)
    assert await prov.http_json("POST", "https://x.example/api?key=SECRET") == (0, None)
    assert "SECRET" not in caplog.text and "key=" not in caplog.text


# --- сервис: кэш и два этапа ---------------------------------------------------------
class Fake(prov.Reputation):
    def __init__(self, name, stage, verdict):
        self.name, self.stage, self.verdict = name, stage, verdict
        self.calls = []

    def enabled(self):
        return True

    async def check_url(self, url):
        self.calls.append(url)
        return self.verdict

    async def check_file(self, sha256):
        self.calls.append(sha256)
        return self.verdict


async def test_answers_are_cached_per_provider(database):
    cheap = Fake("urlhaus", "cheap", Verdict(CLEAN))
    for _ in range(2):
        await service.scan("url", "http://x/", Verdict(), [cheap], now=NOW)
    assert cheap.calls == ["http://x/"]
    await service.scan("url", "http://x/", Verdict(), [cheap], now=NOW + 24 * 3600 + 1)
    assert len(cheap.calls) == 2  # через сутки спросили снова


async def test_cache_does_not_store_raw_urls(database):
    from app.features.linkscan.models import LinkscanCache

    await service.scan(
        "url",
        "http://secret.example/",
        Verdict(),
        [Fake("a", "cheap", Verdict())],
        now=NOW,
    )
    row = await LinkscanCache.first()
    assert row.key != "http://secret.example/" and len(row.key) == 64


async def test_no_answer_is_not_cached(database):
    flaky = Fake("urlhaus", "cheap", None)
    for _ in range(2):
        assert (
            await service.scan("url", "http://x/", Verdict(), [flaky], now=NOW)
        ).level == CLEAN
    assert len(flaky.calls) == 2


async def test_provider_ttl_limits_cache_lifetime(database):
    short = Fake(
        "safebrowsing",
        "cheap",
        Verdict(DANGER, ("phishing",), ("safebrowsing",), ttl=60),
    )
    await service.scan("url", "http://x/", Verdict(), [short], now=NOW)
    await service.scan("url", "http://x/", Verdict(), [short], now=NOW + 30)
    assert len(short.calls) == 1
    cached = await service.scan("url", "http://x/", Verdict(), [short], now=NOW + 31)
    assert cached.level == DANGER and cached.sources == ("safebrowsing",)
    await service.scan("url", "http://x/", Verdict(), [short], now=NOW + 61)
    assert len(short.calls) == 2


async def test_second_stage_only_for_unconfirmed_suspicion(database):
    cheap = Fake("urlhaus", "cheap", Verdict())
    second = Fake(
        "virustotal", "second", Verdict(DANGER, ("flagged",), ("virustotal",))
    )
    providers = [cheap, second]

    clean = await service.scan("url", "http://a/", Verdict(), providers, now=NOW)
    assert clean.level == CLEAN and second.calls == []  # подозрения нет — VT не тратим

    shortener = Verdict(NOTE, ("shortener",), ("local",))
    merged = await service.scan("url", "http://b/", shortener, providers, now=NOW)
    assert second.calls == ["http://b/"]
    assert merged.level == DANGER and merged.reasons == ("shortener", "flagged")


async def test_second_stage_skipped_when_cheap_already_confirms(database):
    cheap = Fake("urlhaus", "cheap", Verdict(DANGER, ("malware",), ("urlhaus",)))
    second = Fake("virustotal", "second", Verdict())
    await service.scan(
        "url", "http://x/", Verdict(NOTE, ("shortener",)), [cheap, second], now=NOW
    )
    assert second.calls == []


async def test_scan_uses_only_enabled_providers(database):
    off = Fake("urlhaus", "cheap", Verdict(DANGER))
    off.enabled = lambda: False
    assert (
        await service.scan("url", "http://x/", Verdict(), [off], now=NOW)
    ).level == CLEAN
    assert off.calls == []


# --- тексты ------------------------------------------------------------------------
def test_texts_exist_in_all_languages():
    codes = {
        "mismatch", "userinfo", "lookalike", "punycode", "shortener", "bad_tld",
        "ip_host", "phishing", "malware", "unwanted", "flagged", "risky_file",
        "double_extension",
    }  # fmt: skip
    for locale, strings in LOCALES.items():
        for code in codes:
            assert f"linkscan.reason.{code}" in strings, (locale, code)
        for kind in ("link", "file"):
            for level in ("danger", "suspicious"):
                assert f"linkscan.headline.{kind}_{level}" in strings


def test_google_attribution_only_when_google_contributed():
    plain = Verdict(SUSPICIOUS, ("mismatch",), ("local",))
    google = Verdict(DANGER, ("phishing",), ("safebrowsing",))
    item = link("paypal.com", "https://evil.example/")
    assert service.link_details(item, plain, "Аня", {}, "ru")["attribution"] == ""
    text = service.link_details(item, google, "Аня", {}, "ru")["attribution"]
    assert "Advisory provided by Google" in text and "developers.google.com" in text


def test_logic_layers_do_not_import_aiogram():
    for name in (
        "models",
        "queries",
        "local",
        "verdict",
        "providers",
        "ratelimit",
        "service",
    ):
        module = importlib.import_module(f"app.features.linkscan.{name}")
        source = Path(module.__file__).read_text(encoding="utf-8")
        assert "import aiogram" not in source and "from aiogram" not in source, name


# --- шаг конвейера -------------------------------------------------------------------
@pytest.fixture
def scans(monkeypatch):
    """Все провайдеры подменены: записываем, что у них спрашивали."""
    cheap = Fake("urlhaus", "cheap", Verdict())
    monkeypatch.setattr("app.features.linkscan.bot.PROVIDERS", (cheap,))
    monkeypatch.setattr("app.features.linkscan.service.PROVIDERS", (cheap,))
    return cheap


def incoming(text, entities, chat_id=7, from_id=7, **kw):
    message = make_message(text, chat_id=chat_id, from_id=from_id, **kw)
    message.entities = entities
    return message


PHISH = "Зайдите paypal.com сейчас"
PHISH_ENT = [ent("text_link", 8, 10, "https://evil.example/login")]


async def test_disabled_by_default(connection, bot, alerts_bot, scans):
    await on_business_message(incoming(PHISH, PHISH_ENT), bot)
    await drain()
    assert alerts_bot.sent == [] and scans.calls == []


async def test_mismatch_alert_through_pipeline(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(incoming(PHISH, PHISH_ENT, first_name="Аня"), bot)
    await drain()
    assert scans.calls == ["https://evil.example/login"]
    (sent,) = alerts_bot.sent
    text = sent["text"]
    assert "Подозрительная ссылка от Аня" in text
    # адрес и текст — моноширинно: Telegram не делает их кликабельными
    assert "<code>https://evil.example/login</code>" in text
    assert "<code>paypal.com</code>" in text and "<code>evil.example</code>" in text
    assert "текст ссылки выглядит как другой адрес" in text
    assert sent["parse_mode"] == "HTML"
    assert await Alert.filter(
        owner_id=OWNER_ID, code="dangerous_link:evil.example"
    ).exists()


async def test_confirmed_danger_uses_cautious_wording(
    connection, bot, alerts_bot, monkeypatch
):
    bad = Fake(
        "safebrowsing", "cheap", Verdict(DANGER, ("phishing",), ("safebrowsing",))
    )
    monkeypatch.setattr("app.features.linkscan.bot.PROVIDERS", (bad,))
    await queries.update_settings(OWNER_ID, enabled=True)
    msg = incoming("http://evil.example/", [ent("url", 0, 19)])
    await on_business_message(msg, bot)
    await drain()
    text = alerts_bot.sent[0]["text"]
    assert "Возможно опасная ссылка" in text and "возможно, фишинг" in text
    assert "возможны ошибки" in text and "Advisory provided by Google" in text


async def test_clean_link_is_silent(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(
        incoming("https://example.com/a", [ent("url", 0, 21)]), bot
    )
    await drain()
    assert alerts_bot.sent == [] and len(scans.calls) == 1


async def test_owner_messages_are_not_scanned(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(incoming(PHISH, PHISH_ENT, from_id=OWNER_ID), bot)
    await drain()
    assert alerts_bot.sent == [] and scans.calls == []


async def test_selected_chats_scope(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True, scope="selected", chats=[8])
    await on_business_message(incoming(PHISH, PHISH_ENT, chat_id=7), bot)
    await on_business_message(incoming(PHISH, PHISH_ENT, chat_id=8, from_id=8), bot)
    await drain()
    assert len(alerts_bot.sent) == 1


async def test_without_external_services_only_local_checks_run(
    connection, bot, alerts_bot, scans
):
    await queries.update_settings(OWNER_ID, enabled=True, external=False)
    await on_business_message(incoming(PHISH, PHISH_ENT), bot)
    await drain()
    assert scans.calls == [] and len(alerts_bot.sent) == 1  # подмену видно и без сети


async def test_trusted_hosts_do_not_spend_requests(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(incoming("https://t.me/durov", [ent("url", 0, 17)]), bot)
    await drain()
    assert scans.calls == []


async def test_link_count_is_capped(connection, bot, alerts_bot, scans, monkeypatch):
    monkeypatch.setattr(settings, "LINKSCAN_MAX_LINKS", 2)
    await queries.update_settings(OWNER_ID, enabled=True)
    text = "a.com b.com c.com d.com"
    entities = [ent("url", i * 6, 5) for i in range(4)]
    await on_business_message(incoming(text, entities), bot)
    await drain()
    assert len(scans.calls) == 2


async def test_caption_entities_are_scanned(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    msg = make_message(None, caption="https://example.org/x", chat_id=7, from_id=7)
    msg.entities, msg.caption_entities = None, [ent("url", 0, 21)]
    await on_business_message(msg, bot)
    await drain()
    assert scans.calls == ["https://example.org/x"]


async def test_scan_failure_does_not_break_the_chain(
    connection, bot, alerts_bot, monkeypatch
):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.features.linkscan.bot.scan_message", boom)
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(
        incoming(PHISH, PHISH_ENT, chat_id=9, from_id=9), bot
    )  # не бросает
    await drain()


async def test_step_does_not_block_the_chain(connection, bot, alerts_bot, monkeypatch):
    gate = asyncio.Event()
    started = []

    async def slow(*a, **k):
        started.append(1)
        await gate.wait()

    monkeypatch.setattr("app.features.linkscan.bot.scan_message", slow)
    await asyncio.wait_for(on_business_message(incoming(PHISH, PHISH_ENT), bot), 1)
    gate.set()
    await drain()
    assert started == [1]


# --- файлы ---------------------------------------------------------------------------
def doc(name, size=1000, unique="u" * 16):
    return types.SimpleNamespace(
        file_id=f"f-{name}", file_unique_id=unique, file_name=name, file_size=size
    )


async def test_risky_file_is_hashed_and_checked(
    connection, bot, alerts_bot, monkeypatch
):
    bad = Fake("urlhaus", "cheap", Verdict(DANGER, ("malware",), ("urlhaus",)))
    monkeypatch.setattr("app.features.linkscan.bot.PROVIDERS", (bad,))
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(make_message(None, document=doc("setup.exe")), bot)
    await drain()
    assert len(bad.calls[0]) == 64  # sha256 файла, а не сам файл
    text = alerts_bot.sent[0]["text"]
    assert "Возможно опасный файл" in text and "<code>setup.exe</code>" in text
    assert f"<code>{bad.calls[0]}</code>" in text
    assert await Alert.filter(
        owner_id=OWNER_ID, code=f"dangerous_file:{'u' * 16}"
    ).exists()


async def test_any_document_is_checked_including_pdf(
    connection, bot, alerts_bot, scans
):
    await queries.update_settings(OWNER_ID, enabled=True)
    for i, name in enumerate(("report.pdf", "photo.jpg", "notes")):
        await on_business_message(
            make_message(None, document=doc(name, unique=f"{i}" * 16)), bot
        )
    await drain()
    assert len(scans.calls) == 3  # хеш каждого документа спросили у дешёвого провайдера


async def test_file_is_streamed_not_buffered(connection, bot, alerts_bot, scans):
    import hashlib

    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(make_message(None, document=doc("a.pdf")), bot)
    await drain()
    assert scans.calls == [hashlib.sha256(b"bytes:files/f-a.pdf").hexdigest()]


async def test_pdf_gets_second_opinion_but_photo_does_not(connection, bot, alerts_bot):
    cheap = Fake("urlhaus", "cheap", Verdict())
    second = Fake(
        "virustotal", "second", Verdict(DANGER, ("malware",), ("virustotal",))
    )
    import app.features.linkscan.bot as linkbot

    linkbot.PROVIDERS = (cheap, second)
    try:
        await queries.update_settings(OWNER_ID, enabled=True)
        await on_business_message(
            make_message(None, document=doc("photo.jpg", unique="p" * 16)), bot
        )
        await on_business_message(
            make_message(None, document=doc("a.pdf", unique="d" * 16)), bot
        )
        await drain()
    finally:
        from app.features.linkscan.providers import PROVIDERS

        linkbot.PROVIDERS = PROVIDERS
    assert len(second.calls) == 1 and len(cheap.calls) == 2
    assert len(alerts_bot.sent) == 1 and "a.pdf" in alerts_bot.sent[0]["text"]


async def test_big_risky_file_is_reported_as_unchecked(
    connection, bot, alerts_bot, scans
):
    await queries.update_settings(OWNER_ID, enabled=True)
    big = 25 * 1024 * 1024
    await on_business_message(
        make_message(None, document=doc("setup.exe", size=big)), bot
    )
    await on_business_message(
        make_message(None, document=doc("movie.mp4", size=big, unique="m" * 16)), bot
    )
    await drain()
    assert scans.calls == []  # скачивать нечего
    (sent,) = alerts_bot.sent  # про mp4 молчим: не группа риска
    assert "Файл не проверен" in sent["text"] and "25 МБ" in sent["text"]
    assert "больше 20 МБ" in sent["text"]


async def test_telegram_refusal_means_unchecked(connection, bot, alerts_bot, scans):
    from aiogram.exceptions import TelegramBadRequest

    async def refuse(file_id):
        raise TelegramBadRequest(method=None, message="file is too big")

    bot.get_file = refuse
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(make_message(None, document=doc("a.zip", size=None)), bot)
    await drain()
    assert "Файл не проверен" in alerts_bot.sent[0]["text"]


async def test_double_extension_alerts_even_without_services(
    connection, bot, alerts_bot, scans
):
    await queries.update_settings(OWNER_ID, enabled=True, external=False)
    await on_business_message(make_message(None, document=doc("счёт.pdf.exe")), bot)
    await drain()
    assert "двойное расширение" in alerts_bot.sent[0]["text"]
    assert scans.calls == []


# --- кнопка «Перейти к сообщению», экранирование, правки -------------------------------
async def test_alert_has_open_message_button(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    msg = incoming(PHISH, PHISH_ENT)
    msg.chat.username = "anya"
    await on_business_message(msg, bot)
    await drain()
    rows = alerts_bot.sent[0]["reply_markup"].inline_keyboard
    assert rows[0][0].url == f"https://t.me/anya/{msg.message_id}"
    assert [b.text for b in rows[1]] == ["Понятно", "Больше не показывать"]


async def test_alert_without_username_uses_the_archive_toast(
    connection, bot, alerts_bot, scans
):
    await queries.update_settings(OWNER_ID, enabled=True)
    await on_business_message(incoming(PHISH, PHISH_ENT), bot)
    await drain()
    button = alerts_bot.sent[0]["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == "archive:link_unavailable"


async def test_foreign_text_is_html_escaped(connection, bot, alerts_bot, scans):
    await queries.update_settings(OWNER_ID, enabled=True)
    entities = [ent("text_link", 8, 10, "https://evil.example/?a=1&b=<2>")]
    await on_business_message(incoming(PHISH, entities), bot)
    await on_business_message(
        make_message(None, document=doc("<b>x</b>.pdf.exe", unique="e" * 16)), bot
    )
    await drain()
    link_text, file_text = (m["text"] for m in alerts_bot.sent)
    assert "a=1&amp;b=&lt;2&gt;" in link_text
    assert "<code>&lt;b&gt;x&lt;/b&gt;.pdf.exe</code>" in file_text


async def test_other_alerts_stay_plain_text(database, alerts_bot):
    from app.features.alerts.bot import report

    await report(OWNER_ID, "command_failed:dice", name="<dice>")
    assert (
        alerts_bot.sent[0]["parse_mode"] is None
        and "<dice>" in alerts_bot.sent[0]["text"]
    )


async def test_edited_message_is_scanned(connection, bot, alerts_bot, scans):
    from aiogram import Bot, Dispatcher, Router
    from aiogram import types as T

    await queries.update_settings(OWNER_ID, enabled=True)
    handled = []
    archive = Router()

    @archive.edited_business_message()
    async def archive_handler(
        message,
    ):  # настоящий обработчик архива не должен пострадать
        handled.append(message.message_id)

    from app.features.linkscan.bot import router as link_router

    dp = Dispatcher()
    dp.include_router(
        Router(name="linkscan_test")
    )  # свежий роутер: у настоящего один родитель
    link_router._parent_router = None
    dp = Dispatcher()
    dp.include_router(link_router)
    dp.include_router(archive)
    fake = Bot("123456:TEST")
    message = T.Message(
        message_id=5,
        date=0,
        chat=T.Chat(id=7, type="private"),
        from_user=T.User(id=7, is_bot=False, first_name="Аня"),
        business_connection_id=connection["connection_id"],
        text=PHISH,
        entities=[
            T.MessageEntity(
                type="text_link", offset=8, length=10, url="https://evil.example/login"
            )
        ],
    )
    try:
        await dp.feed_update(
            fake, T.Update(update_id=1, edited_business_message=message)
        )
        await drain()
    finally:
        link_router._parent_router = None
        await fake.session.close()
    assert handled == [5]  # архив получил правку
    assert scans.calls == ["https://evil.example/login"]
    assert "Подозрительная ссылка" in alerts_bot.sent[0]["text"]


async def test_edit_by_owner_is_not_scanned(connection, bot, alerts_bot, scans):
    from app.features.linkscan.bot import scan_edited

    await queries.update_settings(OWNER_ID, enabled=True)
    msg = incoming(PHISH, PHISH_ENT, from_id=OWNER_ID)
    msg.business_connection_id = connection["connection_id"]
    await scan_edited(bot, msg)
    assert scans.calls == [] and alerts_bot.sent == []


# --- очистка и API -------------------------------------------------------------------
async def test_retention_removes_expired_cache(database):
    from app.features.linkscan.retention import expire_cache

    await queries.put_cached("urlhaus", "url", "a" * 64, 0, [], NOW - 1)
    await queries.put_cached("urlhaus", "url", "b" * 64, 0, [], NOW + 100)
    assert await expire_cache(NOW) == 1
    assert await queries.get_cached("urlhaus", "url", "b" * 64, NOW)


async def test_api_defaults_and_update(client, monkeypatch):
    monkeypatch.setattr(settings, "URLHAUS_AUTH_KEY", "k")
    monkeypatch.setattr(settings, "SAFE_BROWSING_API_KEY", "")
    monkeypatch.setattr(settings, "VT_API_KEY", "")
    first = (await client.get("/api/linkscan", headers=client.owner)).json()
    assert first == {
        "enabled": False,
        "scope": "all",
        "external": True,
        "chats": [],
        "providers": {"urlhaus": True, "safebrowsing": False, "virustotal": False},
    }
    resp = await client.post(
        "/api/linkscan",
        json={"enabled": True, "scope": "selected", "chats": [5, 5, 6]},
        headers=client.owner,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert (body["enabled"], body["scope"], body["chats"]) == (True, "selected", [5, 6])

    # частичное обновление ничего лишнего не сбрасывает
    body = (
        await client.post(
            "/api/linkscan", json={"external": False}, headers=client.owner
        )
    ).json()
    assert body["enabled"] and body["chats"] == [5, 6] and body["external"] is False
    body = (
        await client.post("/api/linkscan", json={"chats": []}, headers=client.owner)
    ).json()
    assert body["chats"] == []


async def test_api_requires_auth_and_valid_scope(client):
    assert (await client.get("/api/linkscan")).status_code == 422
    bad = await client.post("/api/linkscan", json={"scope": "x"}, headers=client.owner)
    assert bad.status_code == 422
