from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from core.context import CommandContext


@dataclass
class Command:
    name: str
    handler: Callable[["CommandContext"], Awaitable[None]]
    module: str
    aliases: list = field(default_factory=list)
    owner_only: bool = True
    # где команда работает: "chat" — в бизнес-чатах (по умолчанию),
    # "bot" — только в личке с ботом, "both" — и там и там
    scope: str = "chat"


class CommandRegistry:
    def __init__(self):
        self._by_alias = {}
        self._modules = {}

    def register(self, cmd: Command):
        self._by_alias[cmd.name] = cmd
        for alias in cmd.aliases:
            self._by_alias[alias] = cmd
        self._modules.setdefault(cmd.module, []).append(cmd)

    def find(self, alias: str):
        return self._by_alias.get(alias)

    def modules(self):
        return self._modules

    def register_passive_module(self, name):
        self._modules.setdefault(name, [])


registry = CommandRegistry()


def command(name, aliases=None, module=None, owner_only=True, scope="chat"):
    def decorator(func):
        registry.register(
            Command(
                name=name,
                handler=func,
                module=module or name,
                aliases=aliases or [],
                owner_only=owner_only,
                scope=scope,
            )
        )
        return func

    return decorator
