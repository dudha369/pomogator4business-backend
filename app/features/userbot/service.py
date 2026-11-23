"""Состояние юзербота для API и бота: единая логика, транспорты тонкие. Без aiogram."""

import asyncio
import time

from app.features.userbot import login, queries
from app.features.userbot.manager import manager
from app.features.vault import service as vault
from config import settings

REMOVE_WAIT = 10  # сколько секунд ждём, пока процесс с блокировкой завершит сеанс


def unavailable_reason() -> str | None:
    """Почему вход невозможен: None — можно."""
    if not settings.USERBOT_CONFIGURED:
        return "not_configured"
    if not vault.enabled():  # строку сессии нельзя хранить открытым текстом
        return "no_encryption"
    return None


async def get_status(owner_id: int) -> dict:
    flow = login.get(owner_id)
    info = await queries.get_info(owner_id)
    status = "none"
    if flow and flow.active:
        status = "login"
    elif info:
        status = _row_status(info)
    return {
        "reason": unavailable_reason(),
        "status": status,
        "username": info["tg_username"] if info else None,
        "login": flow.view() if flow and status in ("login", "none") else None,
    }


def _row_status(info: dict) -> str:
    if info["status"] != "active":
        return info["status"]  # revoked | removing
    return "connected" if info["connected"] else "connecting"


async def start_login(owner_id: int) -> str | None:
    """None — вход начат; иначе код причины отказа."""
    if reason := unavailable_reason():
        return reason
    info = await queries.get_info(owner_id)
    if info and info["status"] == "active":
        return "already_connected"
    if info and info["status"] == "removing":
        return "removing"
    await login.start(owner_id, int(time.time()))
    return None


async def disconnect(owner_id: int) -> None:
    """Отключить и удалить сессию: завершить сеанс в Telegram и стереть строку."""
    await login.cancel(owner_id)
    info = await queries.get_info(owner_id)
    if info is None:
        return
    if info["status"] == "revoked" or not settings.USERBOT_CONFIGURED:
        await queries.delete_session(owner_id)  # завершать нечего или некому
        return
    await queries.set_status(owner_id, "removing")
    manager.nudge()
    for _ in range(REMOVE_WAIT * 2):
        if await queries.get_info(owner_id) is None:
            return
        await asyncio.sleep(0.5)
