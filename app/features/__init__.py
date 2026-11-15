"""Явный список фич (аналог INSTALLED_APPS).

Каждая фича — пакет `app/features/<name>/` с `models.py`, `service.py`, `bot.py`
(команды и роутеры; пакет `bot/`, если файлов много), `api.py` и `locales/`.
Простые команды без состояния живут в `commands/`.
"""

FEATURES = ("games", "mute", "profile", "reminders", "templates")
