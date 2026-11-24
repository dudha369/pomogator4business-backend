"""Единая точка проверки лимитов тарифа. Без aiogram: предупреждение — в `bot.py`."""

import time
from dataclasses import dataclass

from app.features.limits import queries
from app.features.limits.plans import (
    ADMIN,
    METRICS,
    admin_ids,
    limit_for,
    period_start,
)
from app.platform.ttl_cache import ttl_cache


@dataclass(frozen=True)
class Allowed:
    pass


@dataclass(frozen=True)
class Denied:
    metric: str
    limit: int
    used: int
    plan: str
    period: int | None  # начало окна для оконных метрик


@ttl_cache
async def plan_of(owner_id: int) -> dict:
    """{plan, source, expires_at}. Владелец проекта — виртуальный план `admin`;
    нет строки или срок истёк — free (мягко: данные при этом не трогаем)."""
    if owner_id in admin_ids():
        return {"plan": ADMIN, "source": "admin", "expires_at": None}
    row = await queries.get_plan(owner_id)
    if row and (row["expires_at"] is None or row["expires_at"] > time.time()):
        return row
    return {"plan": "free", "source": "free", "expires_at": None}


async def check(
    owner_id: int,
    metric: str,
    need: int = 1,
    current: int | None = None,
    now: int | None = None,
) -> Allowed | Denied:
    """Можно ли владельцу `need` единиц метрики.

    - `state` (зеркала, чаты): сравнивает `current + need` с лимитом; `current`
      передаёт вызывающий (он знает свои таблицы). Ничего не пишет.
    - `window` (проверки Linkscan в сутки): проверка и учёт — один атомарный запрос.
      ВНИМАНИЕ: разрешённая проверка сразу засчитывается; вызывать один раз на действие.
    KeyError — метрика вне `plans.METRICS`."""
    kind = METRICS[metric].kind
    if kind == "value":
        raise ValueError(f"{metric}: это значение плана, а не счётчик (limit_for)")
    plan = (await plan_of(owner_id))["plan"]
    limit = limit_for(plan, metric)
    if limit is None:
        return Allowed()
    if kind == "state":
        if current is None:
            raise ValueError(f"{metric}: для state-метрики нужен current")
        used = current
        if used + need <= limit:
            return Allowed()
        return Denied(metric, limit, used, plan, None)
    now = int(time.time()) if now is None else now  # window
    period = period_start(metric, now)
    if await queries.consume(owner_id, metric, period, need, limit):
        return Allowed()
    used = await queries.get_used(owner_id, metric, period)
    return Denied(metric, limit, used, plan, period)
