from tortoise.exceptions import IntegrityError
from tortoise.expressions import F

from app.features.limits.models import OwnerPlan, UsageCounter
from app.platform.ttl_cache import clear_all


async def get_plan(owner_id: int) -> dict | None:
    rows = await OwnerPlan.filter(owner_id=owner_id).values(
        "plan", "source", "expires_at"
    )
    return rows[0] if rows else None


async def set_plan(
    owner_id: int, plan: str, source: str, expires_at: int | None = None
) -> None:
    await OwnerPlan.update_or_create(
        owner_id=owner_id,
        defaults={"plan": plan, "source": source, "expires_at": expires_at},
    )
    clear_all()


async def get_used(owner_id: int, metric: str, period: int) -> int:
    value = await UsageCounter.filter(
        owner_id=owner_id, metric=metric, period_start=period
    ).values_list("value", flat=True)
    return value[0] if value else 0


async def consume(owner_id: int, metric: str, period: int, need: int, limit: int):
    """Атомарно прибавляет `need`, если лимит не превысится. Проверка и учёт — один
    UPDATE с условием, поэтому две параллельные проверки не проскочат лимит."""
    if need > limit:
        return False
    counter = UsageCounter.filter(owner_id=owner_id, metric=metric, period_start=period)
    fits = counter.filter(value__lte=limit - need)
    if await fits.update(value=F("value") + need):
        return True
    if await counter.exists():  # строка есть, но места нет
        return False
    try:
        await UsageCounter.create(
            owner_id=owner_id, metric=metric, period_start=period, value=need
        )
    except IntegrityError:  # параллельная проверка создала строку раньше
        return bool(await fits.update(value=F("value") + need))
    return True


async def purge_before(period: int) -> int:
    return await UsageCounter.filter(period_start__lt=period).delete()
