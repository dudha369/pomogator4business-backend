"""Тариф владельца и его лимиты (только чтение)."""

import time
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.features.archive import capacity
from app.features.history import rule_queries
from app.features.limits import queries, service
from app.features.limits.plans import METRICS, limit_for, period_start
from app.features.mirror.queries import get_mirror
from app.platform.api.deps import require_user

router = APIRouter()


class LimitOut(BaseModel):
    metric: str
    limit: int | None  # None — без ограничений
    used: int | None  # None — для метрики пока не считается
    period: Literal["day", "current", "plan"]


class PlanOut(BaseModel):
    plan: str
    source: str
    expires_at: int | None
    is_admin: bool
    limits: list[LimitOut]


async def _used(owner_id: int, metric: str, now: int) -> int | None:
    period = period_start(metric, now)
    if period is not None:
        return await queries.get_used(owner_id, metric, period)
    if metric == "mirrors":  # зеркало одно на владельца
        return 1 if await get_mirror(owner_id) else 0
    if metric == "archive_groups":
        return await rule_queries.count_enabled_groups(owner_id)
    if metric in ("archive_entries", "archive_media_bytes"):
        entries, size = await capacity.usage(owner_id)
        return entries if metric == "archive_entries" else size
    return None  # срок хранения — значение плана, не счётчик


@router.get("/plan", response_model=PlanOut)
async def get_plan(user: dict = Depends(require_user)):
    owner_id = user["id"]
    plan = await service.plan_of(owner_id)
    now = int(time.time())
    limits = [
        {
            "metric": name,
            "limit": limit_for(plan["plan"], name),
            "used": await _used(owner_id, name, now),
            "period": {"window": "day", "state": "current", "value": "plan"}[
                metric.kind
            ],
        }
        for name, metric in METRICS.items()
    ]
    return {**plan, "is_admin": plan["source"] == "admin", "limits": limits}
