"""Журнал ошибок и правила оповещений. Без aiogram: отправка — в notify.py."""

import time
from collections import deque
from dataclasses import dataclass

from tortoise.exceptions import IntegrityError
from tortoise.expressions import F

from app.features.ops.models import ErrorEvent
from config import settings

BURST_WINDOW = 300  # секунд, за которые считаем «всплеск»
BURST_PAUSE = 900  # после объявления всплеска обычные оповещения молчат
CRITICAL_REPEAT = 600  # критичная ошибка: повтор не чаще
ACK_SECONDS = 86400
MUTE_SECONDS = 86400


@dataclass
class Item:
    """Накопленные в памяти повторы одного отпечатка между двумя записями в БД."""

    fingerprint: str
    component: str
    kind: str
    place: str
    severity: int
    sample: str
    n: int = 1


@dataclass
class Decision:
    row: ErrorEvent
    kind: str  # "new" | "repeat"
    since: int  # сколько повторов с прошлого оповещения


def decide(
    *,
    critical: bool,
    count: int,
    notified_count: int,
    notified_at: int | None,
    acked_at: int | None,
    muted_until: int | None,
    now: int,
    repeat_seconds: int,
) -> str | None:
    """Нужно ли оповещать об этом отпечатке сейчас (чистая функция).

    Новый — сразу. Повтор — не чаще `repeat_seconds`, не при «Понятно» (сутки) и не при
    «Заглушить». Критичные не глушатся, но повторяются не чаще CRITICAL_REPEAT."""
    if notified_at is None:
        return "new"
    if count <= notified_count:
        return None
    since = now - notified_at
    if critical:
        return "repeat" if since >= CRITICAL_REPEAT else None
    if muted_until and muted_until > now:
        return None
    if acked_at and now - acked_at < ACK_SECONDS:
        return None
    return "repeat" if since >= repeat_seconds else None


class Throttle:
    """Всплеск и потолок обычных оповещений в час. Состояние — в памяти процесса."""

    def __init__(self):
        self.events: deque[tuple[int, int]] = deque()
        self.sent: deque[int] = deque()
        self.burst_until = 0
        self.hidden = 0

    def add_events(self, n: int, now: int) -> bool:
        """True — пора объявить всплеск (один раз за BURST_PAUSE)."""
        self.events.append((now, n))
        while self.events and self.events[0][0] < now - BURST_WINDOW:
            self.events.popleft()
        total = sum(c for _, c in self.events)
        if total >= settings.OPS_BURST_THRESHOLD and now >= self.burst_until:
            self.burst_until = now + BURST_PAUSE
            return True
        return False

    def allow(self, critical: bool, now: int) -> bool:
        if critical:
            return True
        if now < self.burst_until:
            return False
        while self.sent and self.sent[0] < now - 3600:
            self.sent.popleft()
        if len(self.sent) >= settings.OPS_MAX_PER_HOUR:
            self.hidden += 1
            return False
        return True

    def mark_sent(self, critical: bool, now: int) -> None:
        if not critical:
            self.sent.append(now)

    def take_hidden(self) -> int:
        n, self.hidden = self.hidden, 0
        return n


throttle = Throttle()


async def _upsert(item: Item, now: int) -> ErrorEvent:
    build = settings.BUILD
    row = await ErrorEvent.get_or_none(fingerprint=item.fingerprint)
    if row is None:
        try:
            return await ErrorEvent.create(
                fingerprint=item.fingerprint,
                component=item.component,
                kind=item.kind,
                place=item.place,
                severity=item.severity,
                count=item.n,
                first_at=now,
                last_at=now,
                first_build=build,
                last_build=build,
                sample=item.sample,
            )
        except IntegrityError:  # второй процесс (деплой) успел раньше
            row = await ErrorEvent.get(fingerprint=item.fingerprint)
    await ErrorEvent.filter(id=row.id).update(
        count=F("count") + item.n,
        last_at=now,
        last_build=build,
        place=item.place,
        sample=item.sample,
        severity=max(row.severity, item.severity),
    )
    return await ErrorEvent.get(id=row.id)


async def process(items: list[Item], now: int | None = None) -> list[Decision]:
    """Записывает пачку и решает, о чём оповещать (отметка «оповещено» — в notify)."""
    now = int(now if now is not None else time.time())
    decisions = []
    for item in items:
        row = await _upsert(item, now)
        kind = decide(
            critical=row.severity == 1,
            count=row.count,
            notified_count=row.notified_count,
            notified_at=row.notified_at,
            acked_at=row.acked_at,
            muted_until=row.muted_until,
            now=now,
            repeat_seconds=settings.OPS_REPEAT_MINUTES * 60,
        )
        if kind:
            decisions.append(Decision(row, kind, row.count - row.notified_count))
    return decisions


async def mark_notified(row: ErrorEvent, now: int) -> None:
    await ErrorEvent.filter(id=row.id).update(notified_at=now, notified_count=row.count)


async def acknowledge(event_id: int, now: int) -> bool:
    return bool(await ErrorEvent.filter(id=event_id).update(acked_at=now))


async def mute(event_id: int, now: int) -> bool:
    return bool(
        await ErrorEvent.filter(id=event_id).update(muted_until=now + MUTE_SECONDS)
    )


async def top_recent(now: int, window: int = BURST_WINDOW, limit: int = 5):
    return (
        await ErrorEvent.filter(last_at__gte=now - window)
        .order_by("-count")
        .limit(limit)
    )
