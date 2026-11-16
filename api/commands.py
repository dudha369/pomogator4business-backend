"""GET /commands — список всех команд бота для отображения в мини-приложении."""

from fastapi import APIRouter
from pydantic import BaseModel

from app.platform.i18n import t
from app.platform.telegram.registry import registry

router = APIRouter()


class CommandInfo(BaseModel):
    module: str
    name: str
    aliases: list[str]
    title: str
    description: str
    long_description: str
    usage: str
    owner_only: bool
    scope: str


class CommandsOut(BaseModel):
    commands: list[CommandInfo]


@router.get("/commands", response_model=CommandsOut)
async def list_commands(locale: str = "ru"):
    result = []
    for module_name, commands in sorted(registry.modules().items()):
        for cmd in commands:
            result.append(
                {
                    "module": module_name,
                    "name": cmd.name,
                    "aliases": cmd.aliases,
                    "title": t(f"cmdmeta.{cmd.name}.title", locale),
                    "description": t(f"cmdmeta.{cmd.name}.short", locale),
                    "long_description": t(f"cmdmeta.{cmd.name}.long", locale),
                    "usage": t(f"cmdmeta.{cmd.name}.usage", locale),
                    "owner_only": cmd.owner_only,
                    "scope": cmd.scope,
                }
            )
    return {"commands": result}
