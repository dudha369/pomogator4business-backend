"""Настройки подключения: префикс команд, вкл/выкл модулей.

/settings/emoji-status живёт в app/features/emoji_clock/api.py вместе с остальным про
эмодзи-статус, хоть URL и начинается с /settings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.platform.api.deps import Owner, current_owner
from app.platform.telegram.registry import registry
from app.platform.utils import is_valid_prefix
from db.models.connection import set_prefix
from db.models.module_settings import (
    disable_module,
    enable_module,
    list_disabled_modules,
)

router = APIRouter()


class ModuleState(BaseModel):
    name: str
    enabled: bool


class SettingsOut(BaseModel):
    prefix: str
    modules: list[ModuleState]


class ModuleToggle(BaseModel):
    module: str
    enabled: bool


class PrefixOut(BaseModel):
    prefix: str


@router.get("/settings", response_model=SettingsOut)
async def get_settings(owner: Owner = Depends(current_owner)):
    connection = owner.connection
    disabled = await list_disabled_modules(connection["connection_id"])

    modules = sorted(registry.modules().keys())
    return {
        "prefix": connection["prefix"],
        "modules": [
            {"name": module_name, "enabled": module_name not in disabled}
            for module_name in modules
        ],
    }


class PrefixUpdate(BaseModel):
    prefix: str


@router.post("/settings/prefix", response_model=PrefixOut)
async def update_prefix(payload: PrefixUpdate, owner: Owner = Depends(current_owner)):
    if not is_valid_prefix(payload.prefix):
        raise HTTPException(
            status_code=400,
            detail="Prefix must be exactly one character: not a letter, digit or space",
        )

    connection = owner.connection
    await set_prefix(connection["connection_id"], payload.prefix)
    return {"prefix": payload.prefix}


@router.post("/settings/module", response_model=ModuleToggle)
async def toggle_module(payload: ModuleToggle, owner: Owner = Depends(current_owner)):
    if payload.module not in registry.modules():
        raise HTTPException(status_code=404, detail="Unknown module")

    connection = owner.connection
    if payload.enabled:
        await enable_module(connection["connection_id"], payload.module)
    else:
        await disable_module(connection["connection_id"], payload.module)

    return {"module": payload.module, "enabled": payload.enabled}
