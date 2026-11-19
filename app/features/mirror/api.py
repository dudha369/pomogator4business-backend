"""Настройка личного зеркала через мини-приложение — ввод токена напрямую."""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.features.mirror.manager import mirror_manager
from app.features.mirror.queries import delete_mirror, get_mirror
from app.features.mirror.setup import MirrorSetupError, connect_mirror
from app.platform.api.deps import require_user
from app.platform.api.schemas import MirrorStatus

router = APIRouter()


class MirrorState(MirrorStatus):
    # подключено в БД, но вебхук мог не подняться (деплой, нет WEBHOOK_BASE_URL)
    running: bool


class MirrorDisconnected(BaseModel):
    connected: Literal[False]


@router.get("/mirror", response_model=MirrorState)
async def get_mirror_status(user: dict = Depends(require_user)):
    mirror = await get_mirror(user["id"])
    return {
        "connected": bool(mirror and mirror["is_active"]),
        "username": mirror["bot_username"] if mirror else None,
        "running": mirror_manager.is_running(user["id"]),
    }


class MirrorConnect(BaseModel):
    token: str


@router.post("/mirror/connect", response_model=MirrorStatus)
async def api_connect_mirror(
    payload: MirrorConnect, user: dict = Depends(require_user)
):
    try:
        username = await connect_mirror(user["id"], payload.token)
    except MirrorSetupError as exc:
        if exc.code == "start_failed":
            raise HTTPException(status_code=503, detail="start_failed")
        detail = (
            "invalid_format" if exc.code == "invalid_format" else "connection_failed"
        )
        raise HTTPException(status_code=400, detail=detail)

    return {"connected": True, "username": username}


@router.post("/mirror/disconnect", response_model=MirrorDisconnected)
async def api_disconnect_mirror(user: dict = Depends(require_user)):
    await mirror_manager.stop_mirror(user["id"])
    await delete_mirror(user["id"])
    return {"connected": False}
