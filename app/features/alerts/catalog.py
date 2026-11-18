"""Каталог кодов предупреждений: вид и пауза между сообщениями.

Код — `base` или `base:subject` (например `command_failed:dice`: у каждой команды своя
пауза и своё «не показывать»). Тексты — в `locales/alerts.py` по ключам `alert.<base>.*`.
"""

from dataclasses import dataclass
from typing import Literal

from config import settings


@dataclass(frozen=True)
class AlertSpec:
    kind: Literal["event", "state"]
    cooldown_hours: float | None = None  # None — `ALERT_COOLDOWN_HOURS` из настроек


CATALOG: dict[str, AlertSpec] = {
    "command_failed": AlertSpec("event", cooldown_hours=1),
    "no_delete_right": AlertSpec("event"),
    "mirror_not_running": AlertSpec("state"),
    "emoji_access_revoked": AlertSpec("state"),
    "ai_no_key": AlertSpec("state"),
}

MAX_CODE_LEN = 64
MAX_DETAIL_LEN = 200


def base_code(code: str) -> str:
    return code.partition(":")[0]


def spec_for(code: str) -> AlertSpec:
    """KeyError для кода вне каталога: опечатка в коде должна падать в тесте."""
    return CATALOG[base_code(code)]


def cooldown_seconds(code: str) -> int:
    hours = spec_for(code).cooldown_hours
    return int((settings.ALERT_COOLDOWN_HOURS if hours is None else hours) * 3600)
