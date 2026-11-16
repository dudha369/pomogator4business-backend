"""Контракт REST: у каждого эндпоинта есть response_model, схема и TS-типы не устарели."""

import json
from pathlib import Path

from fastapi.routing import APIRoute

from api import _COMMON
from app.features import FEATURES, feature_module
from app.main import app

ROOT = Path(__file__).resolve().parent.parent

# Единственные эндпоинты без response_model: отдают байты, а не JSON.
# Новый сюда не добавлять — описать модель ответа.
BINARY_ENDPOINTS = {
    ("GET", "/avatar/{target_user_id}"),
    ("GET", "/archive/{log_id}/media"),
}


def _routers():
    # FastAPI оборачивает include_router лениво, поэтому app.routes эндпоинтов не покажет:
    # идём по тем же роутерам, что собирает api.setup_routers()
    routers = list(_COMMON)
    for feature in FEATURES:
        module = feature_module(feature, "api")
        if module:
            routers.append(module.router)
    return routers


def _routes(router):
    """Маршруты роутера, включая вложенные (api_export подключён внутри archive/api.py)."""
    for route in router.routes:
        if isinstance(route, APIRoute):
            yield route
        else:  # _IncludedRouter; префиксов у вложенных нет — сверяет test_endpoint_walk_matches_openapi
            yield from _routes(route.original_router)


def _endpoints():
    """(метод, путь без префикса /api, маршрут) для каждого эндпоинта."""
    for router in _routers():
        for route in _routes(router):
            for method in sorted(route.methods - {"HEAD", "OPTIONS"}):
                yield method, route.path, route


def test_every_endpoint_has_response_model():
    missing = [
        f"{method} {path}"
        for method, path, route in _endpoints()
        if route.response_model is None and (method, path) not in BINARY_ENDPOINTS
    ]
    assert not missing, f"нет response_model: {missing}"


def test_endpoint_walk_matches_openapi():
    """Страховка самого теста: обход видит ровно те эндпоинты, что в схеме приложения."""
    walked = {(method, "/api" + path) for method, path, _ in _endpoints()}
    in_schema = {
        (method.upper(), path)
        for path, item in app.openapi()["paths"].items()
        for method in item
    }
    assert walked == in_schema
    assert len(walked) > 40


def test_binary_allowlist_is_not_stale():
    assert BINARY_ENDPOINTS <= {(method, path) for method, path, _ in _endpoints()}


def test_binary_endpoints_describe_their_content():
    for method, path, route in _endpoints():
        if (method, path) in BINARY_ENDPOINTS:
            assert 200 in route.responses, path


def test_webhooks_are_hidden_from_schema():
    assert all(path.startswith("/api/") for path in app.openapi()["paths"])


def test_generated_openapi_is_up_to_date():
    saved = json.loads((ROOT / "generated" / "openapi.json").read_text("utf-8"))
    current = json.loads(json.dumps(app.openapi()))
    assert saved == current, (
        "схема API изменилась: uv run python scripts/export_openapi.py && "
        "npx openapi-typescript generated/openapi.json -o generated/api-types.ts "
        "--default-non-nullable false"
    )
