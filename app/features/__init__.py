"""Явный список фич (аналог INSTALLED_APPS).

Каждая фича — пакет `app/features/<n>/` с `models.py`, `service.py`, `bot.py`
(команды, роутеры, middleware; пакет `bot/`, если файлов много), `api.py` и `locales/`.
Все части, кроме `models.py`, необязательны (у `history` нет ни команд, ни текстов).
Простые команды без состояния живут в `commands/`.
REST — только в `<фича>/api.py` (или пакет `api/`, если роутеров несколько); общий код REST — `app/platform/api/`.
"""

from importlib import import_module
from importlib.util import find_spec

FEATURES = (
    "ai",
    "alerts",
    "archive",
    "autoresponder",
    "chats",
    "connection",
    "custom_emoji",
    "echo",
    "emoji_clock",
    "games",
    "history",
    "limits",
    "linkscan",
    "miniapp",
    "mirror",
    "mute",
    "ops",
    "profile",
    "reminders",
    "scheduled",
    "settings",
    "stats",
    "story",
    "templates",
    "ui_stickers",
    "userbot",
    "vault",
    "voice_effects",
)


def feature_module(feature: str, part: str):
    """`app.features.<feature>.<part>` или None, если у фичи такой части нет."""
    name = f"app.features.{feature}.{part}"
    return import_module(name) if find_spec(name) else None
