"""Контекст лога для апдейтов Telegram (основной бот и зеркала) и ASGI-запросов."""

import uuid

from aiogram import BaseMiddleware
from aiogram.types import Update

from app.features.ops import state
from app.platform import log_context


def _owner_hint(update: Update) -> int | None:
    """Только то, что видно без БД: личное сообщение боту, кнопка, подключение."""
    if update.message and update.message.from_user:
        return update.message.from_user.id
    if update.callback_query:
        return update.callback_query.from_user.id
    if update.business_connection:
        return update.business_connection.user.id
    return None


class OpsContextMiddleware(BaseMiddleware):
    def __init__(self, component: str):
        self.component = component

    async def __call__(self, handler, event: Update, data):
        state.touch_update()
        log_context.bind(
            upd=event.update_id, comp=self.component, owner=_owner_hint(event)
        )
        return await handler(event, data)


class RequestContextMiddleware:
    """Чистый ASGI (не BaseHTTPMiddleware: тот ломает фоновые задачи и contextvars).
    Выдаёт `request_id`, кладёт его в scope["state"] и в заголовок X-Request-ID."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request_id = uuid.uuid4().hex[:12]
        scope.setdefault("state", {})["request_id"] = request_id
        log_context.reset()
        log_context.bind(req=request_id, comp="api")

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_id)
