"""Пользовательские алиасы команд: `.п` → profile и т.п.

Встроенные алиасы (registry) отдаёт /commands; здесь только то, что владелец
добавил сам. Применяются в handlers/business_messages.py."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_connection, require_user
from core import database as db
from core.registry import registry

router = APIRouter()

MAX_ALIASES_PER_OWNER = 30
_ALIAS_RE = re.compile(r"^\S{1,32}$")


def normalize_alias(raw: str, prefix: str) -> str:
    alias = raw.strip().lower()
    # пользователь мог ввести алиас вместе с префиксом (".п") — это не часть имени
    if prefix and alias.startswith(prefix):
        alias = alias[len(prefix):]
    return alias


@router.get("/aliases")
async def list_aliases(user: dict = Depends(require_user)):
    return {"aliases": await db.list_command_aliases(user["id"])}


class AliasCreate(BaseModel):
    command: str
    alias: str


@router.post("/aliases")
async def create_alias(payload: AliasCreate, user: dict = Depends(require_user)):
    connection = await require_connection(user["id"])
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
    if await db.get_command_alias(owner_id, alias) is not None:
        raise HTTPException(status_code=409, detail="Alias already exists")
    if await db.count_command_aliases(owner_id) >= MAX_ALIASES_PER_OWNER:
        raise HTTPException(status_code=400, detail="Too many aliases")

    await db.add_command_alias(owner_id, alias, cmd.name)
    return {"alias": alias, "command": cmd.name}


@router.delete("/aliases/{alias}")
async def delete_alias(alias: str, user: dict = Depends(require_user)):
    if not await db.delete_command_alias(user["id"], alias.strip().lower()):
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"deleted": True}
