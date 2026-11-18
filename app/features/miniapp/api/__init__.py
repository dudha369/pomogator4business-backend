"""REST оболочки мини-приложения: главная, аккаунт, настройки, команды, алиасы, бэкап, пинг."""

from fastapi import APIRouter

from app.features.miniapp.api import (
    account,
    aliases,
    backup,
    commands,
    home,
    locale,
    ping,
    settings,
)

router = APIRouter()
for _module in (locale, commands, settings, account, aliases, ping, backup, home):
    router.include_router(_module.router)
