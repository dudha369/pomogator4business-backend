"""Контекст строки лога: `update_id`, `request_id`, `owner_id`, компонент.

Один изменяемый словарь в ContextVar: внутренние шаги дописывают в него (`bind`), а
задачи, созданные через spawn, наследуют ссылку. Здесь только идентификаторы — текст
сообщений в контекст не кладём никогда."""

import logging
from contextvars import ContextVar

_ctx: ContextVar[dict | None] = ContextVar("log_ctx", default=None)
_ORDER = ("upd", "req", "owner", "comp", "step")


def bind(**values) -> None:
    """Дописывает значения в контекст текущей задачи (None — не трогает)."""
    ctx = _ctx.get()
    if ctx is None:
        ctx = {}
        _ctx.set(ctx)
    ctx.update({k: v for k, v in values.items() if v is not None})


def reset() -> None:
    """Новый пустой контекст (начало запроса): не делит словарь с чужой задачей."""
    _ctx.set({})


def current() -> dict:
    return dict(_ctx.get() or {})


def render(ctx: dict) -> str:
    """`[upd=1 owner=42]` или пустая строка."""
    parts = [f"{k}={ctx[k]}" for k in _ORDER if k in ctx]
    return f"[{' '.join(parts)}] " if parts else ""


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.ctx = render(_ctx.get() or {})
        return True
