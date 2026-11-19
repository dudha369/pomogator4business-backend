"""«Проблемы и настройки» мини-приложения: активные предупреждения и отключённые коды."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.features.alerts import service
from app.platform.api.deps import require_user

router = APIRouter()


class AlertOut(BaseModel):
    id: int
    code: str
    kind: Literal["event", "state"]
    details: dict[str, str]
    count: int
    last_at: int  # unix-секунды


class AlertsOut(BaseModel):
    alerts: list[AlertOut]
    muted: list[str]


class AlertDismissed(BaseModel):
    dismissed: Literal[True]


class AlertMuted(BaseModel):
    muted: str  # отключённый код


class AlertUnmuted(BaseModel):
    unmuted: Literal[True]


@router.get("/alerts", response_model=AlertsOut)
async def get_alerts(user: dict = Depends(require_user)):
    owner_id = user["id"]
    rows = await service.list_active(owner_id)
    return {
        "alerts": [
            {
                "id": r.id,
                "code": r.code,
                "kind": r.kind,
                "details": r.details,
                "count": r.count,
                "last_at": r.last_at,
            }
            for r in rows
        ],
        "muted": await service.list_muted(owner_id),
    }


@router.post("/alerts/{alert_id}/dismiss", response_model=AlertDismissed)
async def dismiss_alert(alert_id: int, user: dict = Depends(require_user)):
    if not await service.dismiss(user["id"], alert_id):
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"dismissed": True}


@router.post("/alerts/{alert_id}/mute", response_model=AlertMuted)
async def mute_alert(alert_id: int, user: dict = Depends(require_user)):
    code = await service.mute(user["id"], alert_id)
    if code is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return {"muted": code}


@router.delete("/alerts/mutes/{code}", response_model=AlertUnmuted)
async def unmute_alert(code: str, user: dict = Depends(require_user)):
    if not await service.unmute(user["id"], code):
        raise HTTPException(status_code=404, detail="Mute not found")
    return {"unmuted": True}
