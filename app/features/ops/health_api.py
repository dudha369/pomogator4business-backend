"""GET /health/deep — корневой маршрут (не /api), скрыт из OpenAPI. Доступ: заголовок
X-Health-Secret (env HEALTH_SECRET) либо initData администратора из ADMIN_USER_IDS."""

import hmac
import json

from fastapi import APIRouter, Header, HTTPException

from app.features.limits.plans import admin_ids
from app.features.ops import health
from app.platform.telegram.auth import validate_init_data
from config import settings

health_router = APIRouter()


def _authorized(secret: str | None, init_data: str | None) -> bool:
    if (
        secret
        and settings.HEALTH_SECRET
        and hmac.compare_digest(secret, settings.HEALTH_SECRET)
    ):
        return True
    if init_data:
        parsed = validate_init_data(init_data, settings.BOT_TOKEN)
        try:
            user = json.loads(parsed["user"]) if parsed else None
        except Exception:
            user = None
        return bool(user and user.get("id") in admin_ids())
    return False


@health_router.get(
    "/health/deep", response_model=health.HealthOut, include_in_schema=False
)
async def health_deep(
    x_health_secret: str | None = Header(default=None),
    x_telegram_init_data: str | None = Header(default=None),
):
    if not _authorized(x_health_secret, x_telegram_init_data):
        raise HTTPException(status_code=403, detail="Forbidden")
    return await health.collect(deep=True)
