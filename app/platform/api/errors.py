"""Единый формат ошибок REST: `{code, message?, request_id, retry_after?, until?, reason?}`.

Тексты для пользователя живут только на фронтенде (RU/EN/UK), бэкенд присылает
КОД. Перечень `ApiErrorCode` попадает в OpenAPI, а оттуда в `generated/` и
TypeScript: таблица экранов на фронтенде типизирована этим перечнем.

Старые места с `HTTPException(detail="…")` менять не нужно: обработчик сам
выводит код из статуса или из прежней причины. Хелпер `api_error` нужен там,
где к коду добавляются данные (`retry_after`, `until`).

`detail` в теле оставлен ещё на один релиз: старый фронтенд читает его, а
бэкенд выкладывается раньше фронтенда.
"""

import logging
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import settings

logger = logging.getLogger("bot.api.errors")


class ApiErrorCode(StrEnum):
    # состояние сервиса и доступ
    maintenance = "maintenance"
    session_expired = "session_expired"
    not_allowed = "not_allowed"
    banned = "banned"  # задача 29: причина (`message`) и срок (`until`)
    feature_disabled = "feature_disabled"  # задача 29: выключено администратором
    limit_reached = "limit_reached"
    rate_limited = "rate_limited"
    # общие по статусу
    bad_request = "bad_request"
    not_found = "not_found"
    conflict = "conflict"
    validation_error = "validation_error"
    upstream_error = "upstream_error"
    internal_error = "internal_error"
    # предметные: их показывает вызывающий экран, а не общий экран ошибки
    start_failed = "start_failed"
    invalid_format = "invalid_format"
    connection_failed = "connection_failed"
    consent_required = "consent_required"
    not_waiting_password = "not_waiting_password"
    userbot_unavailable = "userbot_unavailable"


class ApiErrorOut(BaseModel):
    code: ApiErrorCode
    message: str | None = None  # для логов и разработчика; пользователю не показывается
    request_id: str | None = None
    retry_after: int | None = None  # секунды
    until: int | None = None  # unix-секунды (технический перерыв, срок бана)
    reason: str | None = (
        None  # уточнение предметной ошибки (userbot: причина отказа входа)
    )
    detail: Any | None = (
        None  # прежнее поле FastAPI: только для старого фронтенда, будет убрано
    )


# Прежние причины/строки detail → код (старый формат остаётся рабочим)
_LEGACY_CODES = {
    "maintenance_mode": ApiErrorCode.maintenance,
    "access_denied": ApiErrorCode.not_allowed,
}

_BY_STATUS = {
    400: ApiErrorCode.bad_request,
    401: ApiErrorCode.session_expired,
    403: ApiErrorCode.not_allowed,
    404: ApiErrorCode.not_found,
    409: ApiErrorCode.conflict,
    422: ApiErrorCode.validation_error,
    429: ApiErrorCode.rate_limited,
    502: ApiErrorCode.upstream_error,
    503: ApiErrorCode.upstream_error,
    504: ApiErrorCode.upstream_error,
}


def api_error(
    status_code: int,
    code: ApiErrorCode,
    *,
    message: str | None = None,
    retry_after: int | None = None,
    until: int | None = None,
    reason: str | None = None,
) -> StarletteHTTPException:
    """`raise api_error(429, ApiErrorCode.rate_limited, retry_after=60)`."""
    detail = {
        "code": code.value,
        "message": message,
        "reason": reason,
        "retry_after": retry_after,
        "until": until,
    }
    headers = {"Retry-After": str(retry_after)} if retry_after else None
    return StarletteHTTPException(status_code, detail=detail, headers=headers)


def _code_of(status_code: int, detail: Any) -> ApiErrorCode:
    value = (
        detail.get("code") or detail.get("reason")
        if isinstance(detail, dict)
        else detail
    )
    if isinstance(value, str):
        value = _LEGACY_CODES.get(value, value)
        try:
            return ApiErrorCode(value)
        except ValueError:
            if isinstance(detail, dict) and detail.get("code"):
                # код вне перечня — ошибка разработчика: в журнал ошибок, клиенту — 500
                logger.exception("Неизвестный код ошибки API: %r", value)
                return ApiErrorCode.internal_error
    return _BY_STATUS.get(status_code) or (
        ApiErrorCode.internal_error if status_code >= 500 else ApiErrorCode.bad_request
    )


def _body(request: Request, status_code: int, detail: Any) -> dict:
    extra = detail if isinstance(detail, dict) else {}
    message = extra.get("message") or (detail if isinstance(detail, str) else None)
    reason = extra.get("reason")
    return {
        "code": _code_of(status_code, detail).value,
        "message": message,
        "request_id": getattr(request.state, "request_id", None),
        "retry_after": extra.get("retry_after"),
        "until": extra.get("until"),
        "reason": reason,
        # прежняя форма: {"reason": …} для структурных причин, строка для текстовых
        "detail": {"reason": reason} if reason else message,
    }


def cors_headers(request: Request) -> dict[str, str]:
    """Ответы ServerErrorMiddleware идут МИМО CORSMiddleware: без этих заголовков
    браузер скрывает ответ 500 от скрипта, и фронтенд видит «сеть», а не ошибку."""
    origin = request.headers.get("origin")
    if origin and origin in settings.CORS_ORIGINS:
        return {
            "access-control-allow-origin": origin,
            "access-control-expose-headers": "X-Request-ID",
            "vary": "Origin",
        }
    return {}


async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    headers = {**(exc.headers or {})}
    return JSONResponse(
        _body(request, exc.status_code, exc.detail),
        status_code=exc.status_code,
        headers=headers,
    )


async def validation_error(request: Request, exc: RequestValidationError):
    # только пути полей: значения введённых данных в ответ не возвращаем
    fields = ", ".join(".".join(str(p) for p in e["loc"]) for e in exc.errors())
    return JSONResponse(
        _body(request, 422, {"code": ApiErrorCode.validation_error, "message": fields}),
        status_code=422,
    )


def install_error_handlers(app: FastAPI) -> None:
    app.exception_handler(StarletteHTTPException)(http_error)
    app.exception_handler(RequestValidationError)(validation_error)
