"""Ограничители запросов для платных по лимитам API (VirusTotal: 4/мин, 500/сутки).

Часы подставляются в тестах. Состояние живёт в памяти процесса: после перезапуска счётчик
сутки начинается заново, а настоящий отказ провайдера (429) обрабатывает вызывающий код."""

import asyncio
import time
from collections.abc import Callable


class TokenBucket:
    """Не более `per_minute` запросов в минуту; `acquire` ждёт, но не дольше `max_wait` секунд."""

    def __init__(
        self, per_minute: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._interval = 60.0 / per_minute
        self._capacity = float(per_minute)
        self._tokens = float(per_minute)
        self._clock = clock
        self._stamp = clock()

    def _refill(self) -> None:
        now = self._clock()
        gained = (now - self._stamp) / self._interval
        self._tokens = min(self._capacity, self._tokens + gained)
        self._stamp = now

    def try_acquire(self) -> bool:
        self._refill()
        if self._tokens >= 1:
            self._tokens -= 1
            return True
        return False

    async def acquire(self, max_wait: float = 0) -> bool:
        deadline = self._clock() + max_wait
        while not self.try_acquire():
            wait = self._interval * (1 - self._tokens)
            if self._clock() + wait > deadline:
                return False
            await asyncio.sleep(wait)
        return True


class DailyBudget:
    """Суточный счётчик (сутки по UTC, как у VirusTotal). 0 в `limit` — без лимита."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.time) -> None:
        self.limit = limit
        self._clock = clock
        self._day = -1
        self._used = 0
        self._blocked_day = -1

    def take(self) -> bool:
        day = int(self._clock() // 86400)
        if day != self._day:
            self._day, self._used = day, 0
        if day == self._blocked_day or (self.limit and self._used >= self.limit):
            return False
        self._used += 1
        return True

    def exhaust(self) -> None:
        """Провайдер сам ответил «лимит исчерпан» (429): до конца суток не пробуем."""
        self._blocked_day = int(self._clock() // 86400)
