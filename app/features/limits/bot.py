"""Проверка лимита с предупреждением владельцу (`limit_reached:<metric>`)."""

from app.features.alerts.bot import report
from app.features.limits import service
from app.features.limits.plans import MB, METRICS
from app.platform.i18n import t
from db.models.user_locale import get_locale

# окно уже объявлено владельцу в этом процессе: не дёргаем БД на каждую ссылку
_reported: set[tuple[int, str, int]] = set()


def _amount(metric: str, value: int, locale: str) -> str:
    """Объём — в мегабайтах, остальное числом."""
    if metric.endswith("_bytes"):
        return f"{value / MB:g} {t('limits.unit.mb', locale)}"
    return str(value)


def alert_details(denied: service.Denied, locale: str) -> dict[str, str]:
    metric = denied.metric
    return {
        "label": t(f"limits.metric.{metric}", locale),
        "effect": t(f"limits.effect.{METRICS[metric].effect}", locale),
        "limit": _amount(metric, denied.limit, locale),
        "plan": denied.plan,
    }


async def report_denied(owner_id: int, denied: service.Denied) -> None:
    """Предупреждение об отказе (пауза и «не показывать» — в alerts). Оконные метрики
    объявляются не чаще раза за окно на процесс."""
    key = (owner_id, denied.metric, denied.period or 0)
    if denied.period is not None:
        if key in _reported:
            return
        _reported.add(key)
    details = alert_details(denied, await get_locale(owner_id))
    await report(owner_id, f"limit_reached:{denied.metric}", **details)


async def enforce(
    owner_id: int, metric: str, need: int = 1, current: int | None = None
) -> bool:
    """True — можно. Отказ: один alert, старые данные не трогаем: вызывающий просто
    не делает новое."""
    result = await service.check(owner_id, metric, need, current)
    if isinstance(result, service.Allowed):
        return True
    await report_denied(owner_id, result)
    return False
