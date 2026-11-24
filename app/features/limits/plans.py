"""Метрики, планы и их лимиты. Живут в коде и env, а не в БД: меняются деплоем.

Лимит `None` — без ограничений, `0` — запрещено. В env: `PLAN_LIMITS_FREE="mirrors=1,
linkscan_checks_day=50"`; `-1` значит «без лимита», не названные метрики берут значение
из `DEFAULTS`."""

import logging
from dataclasses import dataclass
from functools import lru_cache
from typing import Literal

from config import settings

logger = logging.getLogger("limits")

PLAN_NAMES = ("free", "pro", "max")
ADMIN = "admin"  # виртуальный план владельца проекта (ADMIN_USER_IDS): без лимитов


@dataclass(frozen=True)
class Metric:
    # state — текущее состояние (чаты, зеркала): считает вызывающий;
    # window — счётчик событий за сутки; value — значение плана, не счётчик
    kind: Literal["state", "window", "value"]
    effect: str = "default"  # ключ текста `limits.effect.<effect>` для предупреждения


METRICS: dict[str, Metric] = {
    # подключены (задача 22)
    "mirrors": Metric("state", "mirrors"),
    "linkscan_checks_day": Metric("window", "linkscan_checks_day"),
    # подготовлены для 17.2 и 26: лимит и тексты есть, проверки в коде ещё нет
    "archive_chats": Metric("state"),
    "archive_groups": Metric("state"),
    "stored_messages": Metric("state"),
    "media_bytes": Metric("state"),
    "retention_days": Metric("value"),
}

# Щедро: всё, что есть сегодня, ничего не теряет. Не названное — без лимита.
DEFAULTS: dict[str, dict[str, int | None]] = {
    "free": {"mirrors": 1, "linkscan_checks_day": 50, "archive_groups": 3},
    "pro": {},
    "max": {},
}

WINDOW_SECONDS = 86400


@lru_cache(maxsize=16)
def _parse(raw: str) -> dict[str, int | None]:
    """Разбор `метрика=число,…`. Опечатку в имени или числе логируем, а не глотаем."""
    out: dict[str, int | None] = {}
    for part in filter(None, (p.strip() for p in raw.split(","))):
        name, _, value = part.partition("=")
        try:
            number = int(value)
        except ValueError:
            number = None
        if name.strip() not in METRICS or number is None:
            logger.warning("PLAN_LIMITS: пропущено %r", part)
            continue
        out[name.strip()] = None if number < 0 else number
    return out


@lru_cache(maxsize=4)
def _ids(raw: str) -> frozenset[int]:
    return frozenset(int(p) for p in raw.split(",") if p.strip().isdigit())


def admin_ids() -> frozenset[int]:
    return _ids(settings.ADMIN_USER_IDS)


def limit_for(plan: str, metric: str) -> int | None:
    """Лимит метрики на плане. KeyError для метрики вне `METRICS` (опечатка в коде)."""
    if metric not in METRICS:
        raise KeyError(metric)
    if plan == ADMIN:
        return None
    plan = plan if plan in PLAN_NAMES else "free"
    overrides = _parse(getattr(settings, f"PLAN_LIMITS_{plan.upper()}"))
    if metric in overrides:
        return overrides[metric]
    return DEFAULTS[plan].get(metric)


def period_start(metric: str, now: int) -> int | None:
    """Начало окна счётчика (сутки по UTC); None — метрика не оконная."""
    if METRICS[metric].kind != "window":
        return None
    return now - now % WINDOW_SECONDS
