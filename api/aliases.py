"""Пользовательские алиасы команд: `.п` → profile и т.п.

Встроенные алиасы (registry) отдаёт /commands; здесь только то, что владелец
добавил сам. Применяются в handlers/business_messages.py."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import Owner, current_owner, require_user
from db.models.command_alias import (
    add_command_alias,
    count_command_aliases,
    delete_command_alias,
    get_command_alias,
    list_command_aliases,
)
from app.platform.telegram.registry import registry

router = APIRouter()

MAX_ALIASES_PER_OWNER = 30
_ALIAS_RE = re.compile(r"^\S{1,32}$")


def normalize_alias(raw: str, prefix: str) -> str:
    alias = raw.strip().lower()
    # пользователь мог ввести алиас вместе с префиксом (".п") — это не часть имени
    if prefix and alias.startswith(prefix):
        alias = alias[len(prefix) :]
    return alias


@router.get("/aliases")
async def list_aliases(user: dict = Depends(require_user)):
    return {"aliases": await list_command_aliases(user["id"])}


class AliasCreate(BaseModel):
    command: str
    alias: str


@router.post("/aliases")
async def create_alias(payload: AliasCreate, owner: Owner = Depends(current_owner)):
    user, connection = owner.user, owner.connection
    owner_id = user["id"]

    cmd = registry.find(payload.command.strip().lower())
    if cmd is None:
        raise HTTPException(status_code=404, detail="Unknown command")

    alias = normalize_alias(payload.alias, connection["prefix"])
    if not _ALIAS_RE.match(alias):
        raise HTTPException(
            status_code=400,
            detail="Alias must be 1-32 characters without spaces",
        )
    if registry.find(alias) is not None:
        raise HTTPException(status_code=409, detail="Alias is already a command name")
    if await get_command_alias(owner_id, alias) is not None:
        raise HTTPException(status_code=409, detail="Alias already exists")
    if await count_command_aliases(owner_id) >= MAX_ALIASES_PER_OWNER:
        raise HTTPException(status_code=400, detail="Too many aliases")

    await add_command_alias(owner_id, alias, cmd.name)
    return {"alias": alias, "command": cmd.name}


@router.delete("/aliases/{alias}")
async def delete_alias(alias: str, user: dict = Depends(require_user)):
    if not await delete_command_alias(user["id"], alias.strip().lower()):
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"deleted": True}
