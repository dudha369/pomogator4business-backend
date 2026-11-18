"""Общие зависимости FastAPI-эндпоинтов: проверка initData мини-приложения
и поиск бизнес-подключения по владельцу. Используется всеми файлами api/*.
"""

import json
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from config import settings
from db.models.connection import get_connection_by_owner
from app.platform.telegram.auth import validate_init_data


def require_user(x_telegram_init_data: str = Header(..., alias="X-Telegram-Init-Data")):
    parsed = validate_init_data(x_telegram_init_data, settings.BOT_TOKEN)
    if not parsed:
        raise HTTPException(status_code=401, detail="Invalid init data")

    try:
        user = json.loads(parsed["user"])
    except Exception:
        raise HTTPException(status_code=401, detail="Missing user in init data")

    if settings.MAINTENANCE_MODE:
        raise HTTPException(status_code=503, detail={"reason": "maintenance_mode"})
    allowed = {
        int(part)
        for part in settings.ALLOWED_USER_IDS.split(",")
        if part.strip().isdigit()
    }
    if allowed and user.get("id") not in allowed:
        raise HTTPException(status_code=403, detail={"reason": "access_denied"})

    return user


async def require_connection(owner_id: int):
    connection = await get_connection_by_owner(owner_id)
    if not connection:
        raise HTTPException(status_code=404, detail="Business connection not found")
    return connection


@dataclass
class Owner:
    """Владелец, открывший мини-приложение, и его бизнес-подключение."""

    user: dict  # данные пользователя из initData (id, имя, язык...)
    connection: dict

    @property
    def id(self) -> int:
        return self.user["id"]


async def current_owner(user: dict = Depends(require_user)) -> Owner:
    """Зависимость для эндпоинтов, которым нужно и подтверждённый пользователь,
    и его бизнес-подключение: один вызов вместо пары require_user +
    require_connection. Нет подключения — 404, как и раньше."""
    return Owner(user=user, connection=await require_connection(user["id"]))
