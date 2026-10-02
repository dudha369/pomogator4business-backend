"""Настройка личного зеркала через мини-приложение — ввод токена напрямую."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from api.deps import require_user
from core import database as db
from core.mirror_manager import mirror_manager
from core.mirror_setup import MirrorSetupError, connect_mirror

router = APIRouter()


@router.get("/mirror")
async def get_mirror_status(user: dict = Depends(require_user)):
    mirror = await db.get_mirror(user["id"])
    return {
        "connected": bool(mirror and mirror["is_active"]),
        "username": mirror["bot_username"] if mirror else None,
    }


class MirrorConnect(BaseModel):
    token: str


@router.post("/mirror/connect")
async def api_connect_mirror(
    payload: MirrorConnect, user: dict = Depends(require_user)
):
    try:
        username = await connect_mirror(user["id"], payload.token)
    except MirrorSetupError as exc:
        detail = (
            "invalid_format" if exc.code == "invalid_format" else "connection_failed"
        )
        raise HTTPException(status_code=400, detail=detail)

    return {"connected": True, "username": username}


@router.post("/mirror/disconnect")
async def api_disconnect_mirror(user: dict = Depends(require_user)):
    await mirror_manager.stop_mirror(user["id"])
    await db.delete_mirror(user["id"])
    return {"connected": False}
