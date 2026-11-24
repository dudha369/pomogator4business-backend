"""Проверка лимита с предупреждением владельцу (`limit_reached:<metric>`)."""

from app.features.alerts.bot import report
from app.features.limits import service
from app.features.limits.plans import METRICS
from app.platform.i18n import t
from db.models.user_locale import get_locale

# окно уже объявлено владельцу в этом процессе: не дёргаем БД на каждую ссылку
_reported: set[tuple[int, str, int]] = set()


def alert_details(denied: service.Denied, locale: str) -> dict[str, str]:
    metric = denied.metric
    return {
        "label": t(f"limits.metric.{metric}", locale),
        "effect": t(f"limits.effect.{METRICS[metric].effect}", locale),
        "limit": str(denied.limit),
        "plan": denied.plan,
    }


async def enforce(
    owner_id: int, metric: str, need: int = 1, current: int | None = None
) -> bool:
    """True — можно. Отказ: один alert (пауза и «не показывать» — в alerts), старые данные
    не трогаем: вызывающий просто не делает новое."""
    result = await service.check(owner_id, metric, need, current)
    if isinstance(result, service.Allowed):
        return True
    key = (owner_id, metric, result.period or 0)
    if result.period is None or key not in _reported:
        if result.period is not None:
            _reported.add(key)
        details = alert_details(result, await get_locale(owner_id))
        await report(owner_id, f"limit_reached:{metric}", **details)
    return False
