"""Сводка здоровья: одна функция для итога запуска, /status и /health/deep."""

import asyncio
import importlib
import time
from typing import Literal

from pydantic import BaseModel

from app.features.ops import startup, state
from app.features.ops.models import ErrorEvent
from app.features.ops.notify import esc
from app.features.userbot.manager import manager as userbot_manager
from app.features.vault import service as vault
from app.features.vault.tables import TABLES
from app.platform import retention
from app.platform.i18n import t
from config import settings

Status = Literal["ok", "warn", "fail", "info"]
_SYMBOL = {"ok": "✓", "warn": "⚠️", "fail": "✗", "info": "ℹ️"}
_CACHE_WEBHOOK = 30
_CACHE_BACKFILL = 300
_cache: dict[str, tuple[float, object]] = {}


class Check(BaseModel):
    name: str
    status: Status
    info: dict[str, str | int | None] = {}


class TopError(BaseModel):
    id: int
    component: str
    kind: str
    place: str
    count: int
    last_at: int


class ErrorsSummary(BaseModel):
    new_24h: int
    events_24h: int
    top: list[TopError]


class RetentionRun(BaseModel):
    at: int
    ok: bool


class HealthOut(BaseModel):
    status: Literal["ok", "degraded", "fail"]
    build: str
    migration: int | None
    migration_repo: int
    uptime_s: int
    checks: list[Check]
    last_update_age_s: int | None = None
    backfill: dict[str, int] | None = None
    retention: dict[str, RetentionRun] = {}
    errors: ErrorsSummary | None = None
    env: dict[str, bool] = {}


async def _cached(key: str, ttl: int, factory):
    hit = _cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = await factory()
    _cache[key] = (time.monotonic() + ttl, value)
    return value


def clear_cache() -> None:
    _cache.clear()


# --- отдельные проверки ----------------------------------------------------------


async def _backfill() -> dict[str, int]:
    async def count() -> dict[str, int]:
        left = {}
        for table in TABLES.values():
            module, cls = table.model.split(":")
            model = getattr(importlib.import_module(module), cls)
            left[table.name] = await model.filter(enc_ver__isnull=True).count()
        return left

    return await _cached("backfill", _CACHE_BACKFILL, count)


async def _webhook_info():
    from bot_instance import bot

    async def get():
        return await asyncio.wait_for(bot.get_webhook_info(), 5)

    return await _cached("webhook", _CACHE_WEBHOOK, get)


async def _check_webhook() -> Check:
    if not settings.WEBHOOK_URL:
        return Check(name="webhook_off", status="info")
    try:
        info = await _webhook_info()
    except Exception as exc:
        return Check(
            name="webhook_error", status="fail", info={"kind": type(exc).__name__}
        )
    if info.url != settings.WEBHOOK_URL:
        return Check(name="webhook_missing", status="fail")
    recent = info.last_error_date and time.time() - _ts(info.last_error_date) < 3600
    if info.last_error_message and recent:
        from app.features.ops.scrub import scrub_text

        return Check(
            name="webhook_error_recent",
            status="warn",
            info={
                "error": scrub_text(info.last_error_message)[:100],
                "pending": info.pending_update_count,
            },
        )
    return Check(
        name="webhook", status="ok", info={"pending": info.pending_update_count}
    )


def _ts(value) -> float:
    return value.timestamp() if hasattr(value, "timestamp") else float(value)


def _check_userbot() -> Check:
    if not settings.USERBOT_CONFIGURED:
        return Check(name="userbot_off", status="info")
    if userbot_manager.holds_lock:
        return Check(
            name="userbot", status="ok", info={"clients": len(userbot_manager.slots)}
        )
    return Check(name="userbot_other", status="info")


def env_flags() -> dict[str, bool]:
    names = (
        "BOT_TOKEN",
        "DB_URL",
        "WEBHOOK_BASE_URL",
        "DATA_MASTER_KEYS",
        "ADMIN_USER_IDS",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "HEALTH_SECRET",
        "URLHAUS_AUTH_KEY",
        "SAFE_BROWSING_API_KEY",
        "VT_API_KEY",
        "AI_API_KEY",
        "CORS_ORIGINS_RAW",
    )
    return {n: bool(getattr(settings, n, "")) for n in names}


def _check_env(flags: dict[str, bool]) -> Check:
    missing = [n for n in ("ADMIN_USER_IDS", "WEBHOOK_BASE_URL") if not flags[n]]
    if missing:
        return Check(
            name="env_missing", status="warn", info={"names": ", ".join(missing)}
        )
    return Check(name="env", status="ok")


async def _vault_checks() -> list[Check]:
    if not vault.enabled():
        return [Check(name="vault_off", status="warn")]
    left = await _backfill()
    checks = [Check(name="vault", status="ok", info={"left": sum(left.values())})]
    if vault.failed_owners:
        checks.append(
            Check(
                name="vault_failed",
                status="warn",
                info={"owners": len(vault.failed_owners)},
            )
        )
    return checks


async def _errors_summary(now: int) -> ErrorsSummary:
    day = now - 86400
    recent = await ErrorEvent.filter(last_at__gte=day).order_by("-count").limit(5)
    return ErrorsSummary(
        new_24h=await ErrorEvent.filter(first_at__gte=day).count(),
        events_24h=await ErrorEvent.filter(last_at__gte=day).count(),
        top=[
            TopError(
                id=r.id,
                component=r.component,
                kind=r.kind,
                place=r.place,
                count=r.count,
                last_at=r.last_at,
            )
            for r in recent
        ],
    )


async def collect(*, deep: bool = False) -> HealthOut:
    now = int(time.time())
    checks: list[Check] = []
    try:
        ms = await startup.check_db()
        checks.append(Check(name="db", status="ok", info={"ms": ms}))
        db_ver = await startup.db_version()
    except startup.DbUnavailable as exc:
        checks.append(Check(name="db", status="fail", info={"kind": str(exc)}))
        db_ver = None
    repo_ver = startup.repo_version()
    if settings.SKIP_MIGRATION_CHECK:
        checks.append(
            Check(
                name="migrations_skipped",
                status="warn",
                info={"db": db_ver, "repo": repo_ver},
            )
        )
    else:
        checks.append(
            Check(
                name="migrations",
                status="ok" if db_ver == repo_ver else "fail",
                info={"db": db_ver, "repo": repo_ver},
            )
        )
    db_ok = checks[0].status == "ok"
    if db_ok:
        checks += await _vault_checks()
    checks.append(await _check_webhook())
    checks.append(_check_userbot())
    flags = env_flags()
    checks.append(_check_env(flags))

    statuses = {c.status for c in checks}
    overall = (
        "fail" if "fail" in statuses else "degraded" if "warn" in statuses else "ok"
    )
    out = HealthOut(
        status=overall,
        build=settings.BUILD,
        migration=db_ver,
        migration_repo=repo_ver,
        uptime_s=int(time.time() - state.started_at),
        checks=checks,
    )
    if deep:
        out.env = flags
        out.last_update_age_s = (
            int(time.time() - state.last_update_at) if state.last_update_at else None
        )
        out.retention = {
            name: RetentionRun(at=at, ok=ok)
            for name, (at, ok) in retention.LAST_RUN.items()
        }
        if db_ok:
            out.backfill = await _backfill() if vault.enabled() else None
            out.errors = await _errors_summary(now)
    return out


# --- текст ------------------------------------------------------------------------


def render_text(report: HealthOut, locale: str, *, started: bool = False) -> str:
    icon = {"ok": "🟢", "degraded": "🟡", "fail": "🔴"}[report.status]
    head = t(
        "ops.status.started" if started else "ops.status.head",
        locale,
        icon=icon,
        build=esc(report.build),
        mig=report.migration if report.migration is not None else "—",
        uptime=report.uptime_s // 60,
    )
    lines = [head, ""]
    for c in report.checks:
        info = {k: esc(v) if v is not None else "—" for k, v in c.info.items()}
        lines.append(f"{_SYMBOL[c.status]} " + t(f"ops.check.{c.name}", locale, **info))
    return "\n".join(lines)
