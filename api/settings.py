"""Настройки подключения: префикс команд, вкл/выкл модулей.

/settings/emoji-status живёт в api/emoji_status.py вместе с остальным про
эмодзи-статус, хоть URL и начинается с /settings."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import Owner, current_owner
from core import database as db
from core.registry import registry

router = APIRouter()


@router.get("/settings")
async def get_settings(owner: Owner = Depends(current_owner)):
    connection = owner.connection
    disabled = await db.list_disabled_modules(connection["connection_id"])

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


@router.post("/settings/prefix")
async def update_prefix(payload: PrefixUpdate, owner: Owner = Depends(current_owner)):
    if len(payload.prefix) != 1:
        raise HTTPException(
            status_code=400, detail="Prefix must be exactly one character"
        )

    connection = owner.connection
    await db.set_prefix(connection["connection_id"], payload.prefix)
    return {"prefix": payload.prefix}


class ModuleToggle(BaseModel):
    module: str
    enabled: bool


@router.post("/settings/module")
async def toggle_module(payload: ModuleToggle, owner: Owner = Depends(current_owner)):
    if payload.module not in registry.modules():
        raise HTTPException(status_code=404, detail="Unknown module")

    connection = owner.connection
    if payload.enabled:
        await db.enable_module(connection["connection_id"], payload.module)
    else:
        await db.disable_module(connection["connection_id"], payload.module)

    return {"module": payload.module, "enabled": payload.enabled}
