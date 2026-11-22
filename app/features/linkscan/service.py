"""Решения linkscan (без aiogram): кэш ответов провайдеров, двухэтапная проверка,
тексты предупреждений."""

import asyncio
import hashlib
import time
from collections.abc import Sequence

from app.features.linkscan import queries
from app.features.linkscan.local import Link
from app.features.linkscan.providers import PROVIDERS, Reputation
from app.features.linkscan.verdict import DANGER, Verdict
from app.platform.i18n import t
from config import settings

LINK_CODE = "dangerous_link"
FILE_CODE = "dangerous_file"
UNCHECKED_CODE = "file_unchecked"


def _cache_ttl(verdict: Verdict) -> int:
    default = int(settings.LINKSCAN_CACHE_TTL_HOURS * 3600)
    return min(default, verdict.ttl) if verdict.ttl is not None else default


async def _ask(provider: Reputation, kind: str, value: str, now: int) -> Verdict | None:
    key = hashlib.sha256(value.encode()).hexdigest() if kind == "url" else value
    cached = await queries.get_cached(provider.name, kind, key, now)
    if cached:
        level = cached["level"]
        return Verdict(
            level, tuple(cached["reasons"]), (provider.name,) if level else ()
        )
    check = provider.check_url if kind == "url" else provider.check_file
    verdict = await check(value)
    if verdict is not None:  # «ответа нет» не кэшируем: в следующий раз спросим снова
        await queries.put_cached(
            provider.name,
            kind,
            key,
            verdict.level,
            verdict.reasons,
            now + _cache_ttl(verdict),
        )
    return verdict


async def scan(
    kind: str,
    value: str,
    local: Verdict,
    providers: Sequence[Reputation] | None = None,
    now: int | None = None,
) -> Verdict:
    """`kind` — "url" или "file" (value — sha256). Дешёвые провайдеры спрашиваем всегда,
    дорогие (VirusTotal) — только если после них остаётся подозрение без подтверждения."""
    now = int(time.time()) if now is None else now
    active = [p for p in (PROVIDERS if providers is None else providers) if p.enabled()]
    verdict = local
    for stage in ("cheap", "second"):
        if stage == "second" and not verdict.needs_second_opinion:
            break
        group = [p for p in active if p.stage == stage]
        for answer in await asyncio.gather(*(_ask(p, kind, value, now) for p in group)):
            if answer is not None:
                verdict = verdict.merge(answer)
    return verdict


# --- тексты предупреждений -----------------------------------------------------------
# Адрес и текст ссылки в предупреждении выводятся моноширинно (`<code>` в шаблонах):
# Telegram не делает такой текст кликабельным, а скопировать его можно одним касанием.
def _headline(kind: str, verdict: Verdict, locale: str) -> str:
    level = "danger" if verdict.level >= DANGER else "suspicious"
    return t(f"linkscan.headline.{kind}_{level}", locale)


def _reasons(verdict: Verdict, locale: str) -> str:
    return "; ".join(t(f"linkscan.reason.{code}", locale) for code in verdict.reasons)


def _common(verdict: Verdict, sender: str, ref: dict, locale: str, kind: str) -> dict:
    return {
        "sender": sender[:40],
        "headline": _headline(kind, verdict, locale),
        "verdict": _reasons(verdict, locale),
        "codes": ",".join(verdict.reasons),
        "level": "danger" if verdict.level >= DANGER else "suspicious",
        **ref,  # msg_id и username: кнопка «Перейти к сообщению»
    }


def link_details(
    link: Link, verdict: Verdict, sender: str, ref: dict, locale: str
) -> dict:
    return {
        **_common(verdict, sender, ref, locale, "link"),
        "display": link.display[:70],
        "url": link.url[:150],
        "domain": link.host,
        # условие Google для предупреждений на основе Safe Browsing
        "attribution": "\n\n" + t("linkscan.google", locale)
        if "safebrowsing" in verdict.sources
        else "",
    }


def file_details(
    name: str, sha256: str, verdict: Verdict, sender: str, ref: dict, locale: str
) -> dict:
    return {
        **_common(verdict, sender, ref, locale, "file"),
        "name": name[:60],
        "sha": sha256 or "—",
    }


def unchecked_details(
    name: str, size_mb: int, verdict: Verdict, sender: str, ref: dict, locale: str
) -> dict:
    return {
        **_common(verdict, sender, ref, locale, "file"),
        "name": name[:60],
        "size": str(size_mb),
    }
