"""Чаты, которые бот видел, и пометка прочитанными из мини-приложения.

Нужно, потому что команду .readall нельзя написать в «Избранном» или в личке
с ботом из бизнес-чата, а список чатов удобнее выбирать глазами."""

import asyncio
import logging
import time

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.features.chats.queries import list_favorite_chat_ids
from app.features.chats.service import ReadFilter, find_chats, read_chats
from app.features.history.service import list_last_incoming_by_chat, list_recent_chats
from app.platform.api.deps import Owner, current_owner
from app.platform.tasks import spawn

router = APIRouter()
logger = logging.getLogger("bot.chats_api")

_WAIT_SECONDS = 20  # меньше клиентского таймаута в 30 с
_jobs: dict[str, dict] = {}  # connection_id -> состояние последнего запуска


class ChatItem(BaseModel):
    chat_id: int
    last_at: int
    last_incoming_at: int | None
    favorite: bool


class ChatsOut(BaseModel):
    chats: list[ChatItem]


class ReadProgress(BaseModel):
    matched: int
    done: int
    failed: int
    # нет у dry_run: там ничего не запускается
    running: bool = False


@router.get("/chats", response_model=ChatsOut)
async def list_chats(owner: Owner = Depends(current_owner)):
    user, connection = owner.user, owner.connection
    chats = await list_recent_chats(connection["connection_id"], 200)
    incoming = {
        row["chat_id"]: row["last_at"]
        for row in await list_last_incoming_by_chat(connection["connection_id"])
    }
    favorites = await list_favorite_chat_ids(user["id"])
    return {
        "chats": [
            {
                "chat_id": chat["chat_id"],
                "last_at": chat["last_at"],
                "last_incoming_at": incoming.get(chat["chat_id"]),
                "favorite": chat["chat_id"] in favorites,
            }
            for chat in chats
        ]
    }


class ReadAllRequest(BaseModel):
    last_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    older_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    exclude_favorites: bool = False
    dry_run: bool = False  # только посчитать, сколько чатов подойдёт


@router.post("/readall", response_model=ReadProgress, response_model_exclude_unset=True)
async def read_all(payload: ReadAllRequest, owner: Owner = Depends(current_owner)):
    connection = owner.connection
    flt = ReadFilter(
        last_seconds=payload.last_hours * 3600 if payload.last_hours else None,
        older_seconds=payload.older_hours * 3600 if payload.older_hours else None,
        exclude_fav=payload.exclude_favorites,
    )

    if payload.dry_run:
        return {
            "matched": len(await find_chats(connection, flt)),
            "done": 0,
            "failed": 0,
        }

    from bot_instance import bot

    connection_id = connection["connection_id"]
    job = _jobs.get(connection_id)
    if job is None or not job["running"]:
        job = _jobs[connection_id] = {
            "running": True,
            "matched": 0,
            "done": 0,
            "failed": 0,
        }
        spawn(_run_job(bot, connection, flt, job), name=f"readall:{connection_id}")

    # На 1000+ чатов прочтение занимает минуты, а у клиента таймаут 30 с: ждём
    # недолго, а если не уложились — отдаём прогресс, работа идёт в фоне.
    deadline = time.monotonic() + _WAIT_SECONDS
    # job — словарь, который целиком уходит в ответ; Event потребовал бы менять его форму
    while job["running"] and time.monotonic() < deadline:  # noqa: ASYNC110
        await asyncio.sleep(0.2)
    return dict(job)


@router.get("/readall/status", response_model=ReadProgress)
async def read_all_status(owner: Owner = Depends(current_owner)):
    job = _jobs.get(owner.connection["connection_id"])
    return (
        dict(job) if job else {"running": False, "matched": 0, "done": 0, "failed": 0}
    )


async def _run_job(bot, connection, flt, job):
    try:
        await read_chats(bot, connection, flt, progress=job)
    except Exception:
        logger.exception("readall: сбой фоновой задачи")
    finally:
        job["running"] = False
