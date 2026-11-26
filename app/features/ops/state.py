"""Состояние процесса для /health/deep: когда запущен и когда был последний апдейт."""

import time

started_at = time.time()
last_update_at: float | None = None


def touch_update() -> None:
    global last_update_at
    last_update_at = time.time()
