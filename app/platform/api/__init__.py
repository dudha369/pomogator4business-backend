"""Сборка REST: роутеры подключаются из `app/features/<f>/api` по списку FEATURES."""

from fastapi import APIRouter

from app.features import FEATURES, feature_module


def setup_routers() -> APIRouter:
    router = APIRouter()
    for feature in FEATURES:
        module = feature_module(feature, "api")
        if module:
            router.include_router(module.router)
    return router
