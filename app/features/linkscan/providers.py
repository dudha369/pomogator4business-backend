"""Провайдеры репутации за общим интерфейсом.

`check_url` / `check_file` возвращают `Verdict` (в т.ч. чистый — «проверили, ничего нет»)
или None — «ответа нет» (нет ключа в запросе, сбой, лимит). None не кэшируется.
Адреса с ключами в логи не попадают: пишем только имя провайдера и статус."""

import base64
import logging
import re
from typing import Any, ClassVar

import aiohttp

from app.features.linkscan.ratelimit import DailyBudget, TokenBucket
from app.features.linkscan.verdict import CLEAN, DANGER, SUSPICIOUS, Verdict
from config import settings

logger = logging.getLogger("bot.linkscan")

TIMEOUT = aiohttp.ClientTimeout(total=8)
NOT_FOUND_TTL = 3600  # «такого адреса ещё не видели» — через час стоит спросить снова


async def http_json(method: str, url: str, **kwargs) -> tuple[int, Any]:
    """(статус, JSON или None). Сетевая ошибка → (0, None). Вынесено ради тестов."""
    try:
        async with (
            aiohttp.ClientSession(timeout=TIMEOUT) as session,
            session.request(method, url, **kwargs) as resp,
        ):
            try:
                return resp.status, await resp.json(content_type=None)
            except Exception:
                return resp.status, None
    except Exception as error:  # текст ошибки aiohttp может содержать адрес с ключом
        logger.warning(
            "Запрос к %s не удался: %s", url.split("?")[0], type(error).__name__
        )
        return 0, None


class Reputation:
    name = ""
    stage = "cheap"  # "cheap" — всегда; "second" — только при подозрении

    def enabled(self) -> bool:
        return False

    async def check_url(self, url: str) -> Verdict | None:
        return None

    async def check_file(self, sha256: str) -> Verdict | None:
        return None


class URLhaus(Reputation):
    name = "urlhaus"
    BASE = "https://urlhaus-api.abuse.ch/v1"

    def enabled(self) -> bool:
        return bool(settings.URLHAUS_AUTH_KEY)

    async def _post(self, path: str, data: dict) -> dict | None:
        status, body = await http_json(
            "POST",
            f"{self.BASE}/{path}/",
            data=data,
            headers={"Auth-Key": settings.URLHAUS_AUTH_KEY},
        )
        return body if status == 200 and isinstance(body, dict) else None

    async def check_url(self, url: str) -> Verdict | None:
        body = await self._post("url", {"url": url})
        match (body or {}).get("query_status"):
            case "ok":
                online = body.get("url_status") == "online"
                return Verdict(
                    DANGER if online else SUSPICIOUS, ("malware",), (self.name,)
                )
            case "no_results":
                return Verdict()
        return None

    async def check_file(self, sha256: str) -> Verdict | None:
        body = await self._post("payload", {"sha256_hash": sha256})
        match (body or {}).get("query_status"):
            case "ok":
                return Verdict(DANGER, ("malware",), (self.name,))
            case "no_results":
                return Verdict()
        return None


class SafeBrowsing(Reputation):
    name = "safebrowsing"
    URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
    REASONS: ClassVar[dict[str, str]] = {
        "SOCIAL_ENGINEERING": "phishing",
        "MALWARE": "malware",
        "UNWANTED_SOFTWARE": "unwanted",
        "POTENTIALLY_HARMFUL_APPLICATION": "malware",
    }

    def enabled(self) -> bool:
        return bool(settings.SAFE_BROWSING_API_KEY)

    async def check_url(self, url: str) -> Verdict | None:
        payload = {
            "client": {"clientId": "pomogator4business", "clientVersion": "1.0"},
            "threatInfo": {
                "threatTypes": list(self.REASONS),
                "platformTypes": ["ANY_PLATFORM"],
                "threatEntryTypes": ["URL"],
                "threatEntries": [{"url": url}],
            },
        }
        status, body = await http_json(
            "POST",
            self.URL,
            params={"key": settings.SAFE_BROWSING_API_KEY},
            json=payload,
        )
        if status != 200 or not isinstance(body, dict):
            return None
        matches = body.get("matches") or []
        if not matches:
            return Verdict()
        reasons = tuple(
            dict.fromkeys(
                self.REASONS.get(m.get("threatType"), "malware") for m in matches
            )
        )
        # условие Google: нельзя показывать ответ старше `cacheDuration`
        ttl = min((_seconds(m.get("cacheDuration")) for m in matches), default=None)
        return Verdict(DANGER, reasons, (self.name,), ttl=ttl)


def _seconds(duration: str | None) -> int:
    match = re.fullmatch(r"(\d+(?:\.\d+)?)s", duration or "")
    return int(float(match.group(1))) if match else 300


# --- VirusTotal ----------------------------------------------------------------------
# Порог: «3 из 91» бывает ложным срабатыванием, поэтому опасным считаем несколько
# детектов или известную категорию, а один-два детекта — только подозрением.
VT_DANGER_MIN = 5
VT_SUSPICIOUS_MIN = 2  # для адресов; для файлов — VT_FILE_SUSPICIOUS_MIN
VT_FILE_SUSPICIOUS_MIN = 3
VT_CATEGORY_MIN = 2
VT_MAX_WAIT = 20  # секунд ждём свободного места под 4 запроса/мин


class VirusTotal(Reputation):
    name = "virustotal"
    stage = "second"
    BASE = "https://www.virustotal.com/api/v3"

    def __init__(self) -> None:
        self.bucket = TokenBucket(4)
        self.daily = DailyBudget(settings.LINKSCAN_VT_DAILY_LIMIT)

    def enabled(self) -> bool:
        return bool(settings.VT_API_KEY) and settings.LINKSCAN_VT_ENABLED

    async def _get(self, path: str) -> tuple[int, Any]:
        if not self.daily.take() or not await self.bucket.acquire(VT_MAX_WAIT):
            return 0, None
        status, body = await http_json(
            "GET", f"{self.BASE}/{path}", headers={"x-apikey": settings.VT_API_KEY}
        )
        if status == 429:
            self.daily.exhaust()
        return status, body

    async def check_url(self, url: str) -> Verdict | None:
        # только поиск готового отчёта: адрес на анализ не отправляем (отправка
        # сделала бы адрес из личной переписки доступным другим пользователям VT)
        ident = base64.urlsafe_b64encode(url.encode()).decode().rstrip("=")
        status, body = await self._get(f"urls/{ident}")
        return self._parse(status, body, url_mode=True)

    async def check_file(self, sha256: str) -> Verdict | None:
        status, body = await self._get(f"files/{sha256}")
        return self._parse(status, body, url_mode=False)

    def _parse(self, status: int, body: Any, *, url_mode: bool) -> Verdict | None:
        if status == 404:
            return Verdict(ttl=NOT_FOUND_TTL)
        attrs = (
            ((body or {}).get("data") or {}).get("attributes")
            if status == 200
            else None
        )
        if not isinstance(attrs, dict):
            return None
        stats = attrs.get("last_analysis_stats") or {}
        bad = stats.get("malicious", 0) + stats.get("suspicious", 0)
        results = (attrs.get("last_analysis_results") or {}).values()
        text = [str(r.get("result") or "").lower() for r in results]
        phishing = sum("phish" in s for s in text)
        malware = sum("malware" in s or "malicious" in s for s in text)

        reasons: list[str] = []
        if url_mode and phishing >= VT_CATEGORY_MIN:
            reasons.append("phishing")
        if malware >= VT_CATEGORY_MIN or (not url_mode and bad >= VT_DANGER_MIN):
            reasons.append("malware")
        if stats.get("malicious", 0) >= VT_DANGER_MIN or reasons:
            return Verdict(DANGER, tuple(reasons) or ("flagged",), (self.name,))
        if bad >= (VT_SUSPICIOUS_MIN if url_mode else VT_FILE_SUSPICIOUS_MIN):
            return Verdict(SUSPICIOUS, ("flagged",), (self.name,))
        return Verdict(CLEAN, (), (self.name,))


PROVIDERS: tuple[Reputation, ...] = (URLhaus(), SafeBrowsing(), VirusTotal())
