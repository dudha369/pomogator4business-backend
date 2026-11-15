"""Общий контроль спам-рассылок — и для основного бота (commands/spam.py),
и для зеркала (mirror/spam.py):

- не даёт запустить вторую рассылку, пока не закончилась первая (на один
  и тот же "scope" — connection_id для основного бота, свой mirror-бот
  владельца для зеркала);
- clamp() подрезает запрошенное количество до лимита.

Хранится в памяти процесса — этого достаточно для одного воркера.
"""

_active: set[str] = set()


def is_spam_active(scope: str) -> bool:
    return scope in _active


def start_spam(scope: str) -> None:
    _active.add(scope)


def stop_spam(scope: str) -> None:
    _active.discard(scope)


def clamp(requested: int, limit: int) -> int:
    return max(0, min(requested, limit))
