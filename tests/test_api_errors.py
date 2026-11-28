"""Единый формат ошибок API (задача 33): коды, request_id, retry_after, совместимость."""

import logging

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from app.features.ops.middleware import RequestContextMiddleware
from app.platform.api import setup_routers
from app.platform.api.errors import (
    ApiErrorCode,
    api_error,
    install_error_handlers,
)
from config import settings
from tests.conftest import init_data_headers

pytestmark = pytest.mark.asyncio


class _Body(BaseModel):
    n: int


def _mini() -> FastAPI:
    """Приложение только с обработчиками: проверяем формат, а не конкретные эндпоинты."""
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)

    @app.get("/code/{code}/{status}")
    async def by_code(code: str, status: int):
        raise api_error(status, ApiErrorCode(code))

    @app.get("/text/{status}")
    async def text(status: int):
        raise HTTPException(status, detail="Some English text")

    @app.get("/legacy/{value}")
    async def legacy(value: str):
        raise HTTPException(409, detail={"reason": value})

    @app.get("/str/{value}")
    async def string_code(value: str):
        raise HTTPException(403, detail=value)

    @app.get("/rate")
    async def rate():
        raise api_error(429, ApiErrorCode.rate_limited, retry_after=42)

    @app.get("/maintenance")
    async def maintenance():
        raise api_error(
            503,
            ApiErrorCode.maintenance,
            message="Обновляем базу",
            until=1_800_000_000,
            reason="maintenance_mode",
        )

    @app.get("/unknown-code")
    async def unknown():
        raise HTTPException(400, detail={"code": "no_such_code"})

    @app.post("/body")
    async def body(payload: _Body):
        return payload

    return app


@pytest.fixture
async def mini():
    transport = httpx.ASGITransport(app=_mini())
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest.mark.parametrize("code", list(ApiErrorCode))
async def test_every_code_reaches_the_client(mini, code):
    res = await mini.get(f"/code/{code.value}/400")
    body = res.json()
    assert body["code"] == code.value
    assert body["request_id"] == res.headers["x-request-id"]


@pytest.mark.parametrize(
    ("status", "code"),
    [
        (400, "bad_request"),
        (401, "session_expired"),
        (403, "not_allowed"),
        (404, "not_found"),
        (409, "conflict"),
        (422, "validation_error"),
        (429, "rate_limited"),
        (502, "upstream_error"),
        (503, "upstream_error"),
        (418, "bad_request"),
        (500, "internal_error"),
    ],
)
async def test_free_text_detail_gets_code_from_status(mini, status, code):
    res = await mini.get(f"/text/{status}")
    body = res.json()
    assert res.status_code == status
    assert body["code"] == code
    assert body["message"] == "Some English text"
    assert body["detail"] == "Some English text"  # старый фронтенд читает detail


async def test_unknown_route_is_not_found(mini):
    res = await mini.get("/nothing-here")
    assert res.status_code == 404
    assert res.json()["code"] == "not_found"


async def test_legacy_reasons_map_to_codes_and_keep_old_shape(mini):
    body = (await mini.get("/legacy/maintenance_mode")).json()
    assert body["code"] == "maintenance"
    assert body["detail"] == {"reason": "maintenance_mode"}
    body = (await mini.get("/legacy/access_denied")).json()
    assert body["code"] == "not_allowed"
    assert body["detail"] == {"reason": "access_denied"}
    # причина вне перечня: код по статусу, причина доезжает до фронтенда
    body = (await mini.get("/legacy/no_encryption")).json()
    assert body["code"] == "conflict" and body["reason"] == "no_encryption"
    assert body["detail"] == {"reason": "no_encryption"}


async def test_string_detail_that_is_a_code(mini):
    body = (await mini.get("/str/limit_reached")).json()
    assert body["code"] == "limit_reached"
    assert body["detail"] == "limit_reached"


async def test_rate_limited_carries_retry_after_and_header(mini):
    res = await mini.get("/rate")
    assert res.status_code == 429
    assert res.json()["retry_after"] == 42
    assert res.headers["retry-after"] == "42"


async def test_maintenance_carries_until_and_message(mini):
    res = await mini.get("/maintenance")
    body = res.json()
    assert res.status_code == 503
    assert body["code"] == "maintenance"
    assert body["until"] == 1_800_000_000
    assert body["message"] == "Обновляем базу"
    assert body["detail"] == {"reason": "maintenance_mode"}


async def test_unknown_code_goes_to_error_log_and_client_gets_internal(mini, caplog):
    with caplog.at_level(logging.ERROR, logger="bot.api.errors"):
        res = await mini.get("/unknown-code")
    assert res.json()["code"] == "internal_error"
    # logger.exception → журнал ошибок наблюдаемости (ERROR с exc_info... или текстом)
    assert any("Неизвестный код ошибки API" in r.message for r in caplog.records)


async def test_validation_error_does_not_echo_input(mini):
    secret = "SECRET-VALUE-123"
    res = await mini.post("/body", json={"n": secret})
    body = res.json()
    assert res.status_code == 422
    assert body["code"] == "validation_error"
    assert "body.n" in body["message"]
    assert secret not in res.text


async def test_500_has_cors_headers_only_for_allowed_origin(monkeypatch):
    """500 отдаёт ServerErrorMiddleware мимо CORS: без заголовков браузер показал бы
    «сеть» вместо ошибки сервера."""
    from app.main import unhandled_error

    monkeypatch.setattr(settings, "CORS_ORIGINS_RAW", "https://app.example")
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    app.exception_handler(Exception)(unhandled_error)

    @app.get("/boom")
    async def boom():
        raise RuntimeError("x")

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        ok = await c.get("/boom", headers={"Origin": "https://app.example"})
        other = await c.get("/boom", headers={"Origin": "https://evil.example"})
    assert ok.json()["code"] == "internal_error"
    assert ok.headers["access-control-allow-origin"] == "https://app.example"
    assert "x-request-id" in ok.headers
    assert "access-control-allow-origin" not in other.headers


# --- настоящие эндпоинты ---------------------------------------------------------


@pytest.fixture
async def real(connection):
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)
    install_error_handlers(app)
    app.include_router(setup_routers(), prefix="/api")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        c.owner = init_data_headers()
        yield c


async def test_real_maintenance_mode(real, monkeypatch):
    monkeypatch.setattr(settings, "MAINTENANCE_MODE", True)
    res = await real.get("/api/account", headers=real.owner)
    body = res.json()
    assert res.status_code == 503
    assert body["code"] == "maintenance"
    assert body["detail"] == {"reason": "maintenance_mode"}
    assert body["request_id"] == res.headers["x-request-id"]


async def test_real_not_allowed(real, monkeypatch):
    monkeypatch.setattr(settings, "ALLOWED_USER_IDS", "1")
    res = await real.get("/api/account", headers=real.owner)
    assert res.status_code == 403 and res.json()["code"] == "not_allowed"


async def test_real_bad_init_data_is_session_expired(real):
    res = await real.get("/api/account", headers={"X-Telegram-Init-Data": "junk"})
    assert res.status_code == 401 and res.json()["code"] == "session_expired"


async def test_real_missing_init_data_is_validation_error(real):
    res = await real.get("/api/account")
    assert res.status_code == 422
    assert res.json()["code"] == "validation_error"


async def test_real_export_already_running_has_retry_after(real, monkeypatch):
    from app.features.archive import api_export

    monkeypatch.setattr(api_export, "_running", {42})
    res = await real.post("/api/archive/export", json={}, headers=real.owner)
    assert res.status_code == 429
    assert res.json()["code"] == "rate_limited"
    assert res.json()["retry_after"] == 30


async def test_schema_exposes_codes():
    from app.main import app

    schemas = app.openapi()["components"]["schemas"]
    assert set(schemas["ApiErrorCode"]["enum"]) == {c.value for c in ApiErrorCode}
    assert "ApiErrorOut" in schemas
