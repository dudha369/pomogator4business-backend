"""Что делает юзербот с событиями Telegram: новые, изменённые, удалённые сообщения.

Здесь нет ни Telethon (адаптер присылает готовые `UbMessage`), ни отправки в Telegram
(этим занят `notices`). Запись идёт через общий `ingest`: правила чатов, шифрование
vault и приоритет бизнес-бота работают так же, как для бизнес-бота."""

import asyncio
import logging

from app.features.archive import service
from app.features.history import rules
from app.features.history import service as history
from app.features.history.ingest import ingest
from app.features.history.snapshot import FILE_KINDS, entry_snapshot
from app.features.userbot import burst, notices
from app.features.userbot.ub_types import UbMessage
from app.platform.sources import userbot_connection_id
from app.platform.tasks import spawn
from config import settings

logger = logging.getLogger("bot.userbot.events")

# файлы, которые сейчас скачиваются: (подключение, чат, сообщение) -> задача
_inflight: dict[tuple[str, int, int], asyncio.Task] = {}
_download_slots: dict[int, asyncio.Semaphore] = {}
_MAX_PARALLEL_DOWNLOADS = 2
_PENDING_WAIT = 10  # столько удаление ждёт файл, который ещё скачивается


class Sink:
    """Получатель событий клиента (`RunningClient.listen`)."""

    def __init__(self, owner_id: int):
        self.owner_id = owner_id

    async def wants(self, chat_id: int, kind: str) -> bool:
        """Ранний фильтр: Telegram присылает обновления по ВСЕМ диалогам аккаунта,
        выключенные чаты должны обходиться без сборки снимка и без записи."""
        return await rules.should_archive(self.owner_id, chat_id, kind, "userbot")

    async def new(self, msg: UbMessage) -> None:
        await handle_new(self.owner_id, msg)

    async def edited(self, msg: UbMessage) -> None:
        await handle_edited(self.owner_id, msg)

    async def deleted(self, chat_id: int | None, ids: list[int]) -> None:
        await handle_deleted(self.owner_id, chat_id, ids)


def _with_meta(msg: UbMessage) -> dict:
    """Снимок + название чата и автор (raw_json: по нему заголовки уведомлений и веб
    показывают чат, который бот сам не видит; шифруется, как и остальное содержимое)."""
    snap = dict(msg.snapshot)
    snap["raw_json"] = {
        "chat": {
            "id": msg.chat.id,
            "type": msg.chat.kind,
            "title": msg.chat.title,
            "username": msg.chat.username,
        },
        "from": {
            "id": msg.sender_id,
            "name": msg.sender_name,
            "username": msg.sender_username,
        },
    }
    return snap


def _media_plan(snap: dict, rule: rules.Rule) -> tuple[dict | None, bool]:
    """(поля media для записи, нужно ли скачивать файл)."""
    kind = snap.get("kind")
    if kind not in FILE_KINDS:
        return None, False
    base = {
        "media_type": kind,
        "media_mime": snap.get("media_mime"),
        "media_name": snap.get("media_name"),
    }
    if not rule.media:
        return {**base, "media_status": "disabled"}, False
    size = snap.get("file_size") or 0
    if size > settings.USERBOT_MEDIA_MAX_BYTES:
        return {**base, "media_status": "too_large"}, False
    return {**base, "media_status": "pending"}, True


async def handle_new(owner_id: int, msg: UbMessage) -> None:
    rule = await rules.rule_for(owner_id, msg.chat.id, msg.chat.kind, "userbot")
    if not rule.enabled:
        return
    snap = _with_meta(msg)
    media, fetch = _media_plan(snap, rule)
    connection_id = userbot_connection_id(owner_id)
    written = await ingest(
        source="userbot",
        connection_id=connection_id,
        chat_id=msg.chat.id,
        message_id=msg.message_id,
        is_owner=msg.is_out,
        text=snap["text"],
        ts=msg.ts,
        snapshot=snap,
        media=media,
        chat_kind=msg.chat.kind,
    )
    if written and fetch and msg.download:
        _start_download(connection_id, msg)


def _start_download(connection_id: str, msg: UbMessage) -> None:
    key = (connection_id, msg.chat.id, msg.message_id)
    task = spawn(_download(key, msg), name="userbot-media")
    _inflight[key] = task


def _slot() -> asyncio.Semaphore:
    loop_id = id(asyncio.get_running_loop())
    if loop_id not in _download_slots:
        _download_slots.clear()  # семафор привязан к циклу: старые не нужны
        _download_slots[loop_id] = asyncio.Semaphore(_MAX_PARALLEL_DOWNLOADS)
    return _download_slots[loop_id]


async def _download(key: tuple[str, int, int], msg: UbMessage) -> None:
    """Скачивает файл и дописывает байты в уже записанную строку истории."""
    connection_id, chat_id, message_id = key
    status = "failed"
    try:
        async with _slot():
            data = await asyncio.wait_for(
                msg.download(), settings.USERBOT_MEDIA_TIMEOUT
            )
        if data is not None and len(data) > settings.USERBOT_MEDIA_MAX_BYTES:
            status, data = "too_large", None  # размер в снимке бывает неточным
        if data:
            if await history.attach_media(
                connection_id, chat_id, message_id, data, "saved"
            ):
                return
            status = "failed"
        await history.set_media_status(connection_id, chat_id, message_id, status)
    except Exception as exc:
        logger.warning("Файл юзербота не скачан (%s)", type(exc).__name__)
        try:
            await history.set_media_status(connection_id, chat_id, message_id, "failed")
        except Exception:
            logger.debug("статус файла не записан", exc_info=True)
    finally:
        _inflight.pop(key, None)


async def _wait_downloads(connection_id: str, message_ids) -> None:
    """Сообщение могли удалить, пока его файл ещё скачивается: даём ему дойти."""
    ids = set(message_ids)
    tasks = [t for k, t in _inflight.items() if k[0] == connection_id and k[2] in ids]
    if tasks:
        await asyncio.wait(tasks, timeout=_PENDING_WAIT)


# --- правки --------------------------------------------------------------------------


async def handle_edited(owner_id: int, msg: UbMessage) -> None:
    rule = await rules.rule_for(owner_id, msg.chat.id, msg.chat.kind, "userbot")
    if not rule.enabled or not await notices.archive_enabled(owner_id):
        return
    snap = _with_meta(msg)
    connection_id = userbot_connection_id(owner_id)
    chat_id, message_id = msg.chat.id, msg.message_id
    plan = await service.plan_edit(
        notices.synthetic_connection(owner_id),
        chat_id,
        message_id,
        owner_id if msg.is_out else (msg.sender_id or 0),
        snap,
        bot_edit=False,
    )
    # настройки архива — с бизнес-подключения (у `ub:` своей строки нет)
    plan.prefs = await notices.prefs_for(owner_id)
    # notify здесь = «записать правку в архив»; присылать ли уведомление — решает чат
    plan.notify = bool(plan.change) and (not plan.is_owner or plan.prefs.own_edits)
    notice_id = None
    if plan.notify and rule.notify:
        previous = await service.previous_edits(connection_id, chat_id, message_id)
        notice_id = await notices.send_edit(owner_id, msg, plan, snap, previous)
    await service.record_edit(connection_id, chat_id, message_id, plan, snap, notice_id)
    if plan.change in ("media", "media_caption") and msg.download:
        _, fetch = _media_plan(snap, rule)  # файл заменили: байты старого неверны
        if fetch:
            await history.set_media_status(
                connection_id, chat_id, message_id, "pending"
            )
            _start_download(connection_id, msg)


# --- удаления ------------------------------------------------------------------------


async def handle_deleted(owner_id: int, chat_id: int | None, ids: list[int]) -> None:
    connection_id = userbot_connection_id(owner_id)
    await _wait_downloads(connection_id, ids)
    if chat_id is not None:  # каналы и супергруппы
        found = await service.collect_deleted(
            connection_id, chat_id, ids, lambda _message_id: False
        )
        groups = {chat_id: found} if found else {}
    else:  # личные чаты и малые группы: только номера, ищем по ним
        groups = {}
        for entry in await history.find_userbot_by_ids(connection_id, ids):
            item = (entry["message_id"], entry, entry_snapshot(entry))
            groups.setdefault(entry["chat_id"], []).append(item)
    # форма события — для проверки на проде гипотезы «без chat_id»; без содержимого
    logger.info(
        "Удаление (юзербот %s): chat_id=%s, номеров=%d, найдено в истории=%d",
        owner_id,
        "есть" if chat_id is not None else "нет",
        len(ids),
        sum(len(v) for v in groups.values()),
    )
    if not groups or not await notices.archive_enabled(owner_id):
        return
    for cid, found in groups.items():
        await _process_chat(owner_id, connection_id, cid, found)


async def _process_chat(owner_id, connection_id, chat_id, found) -> None:
    chat_meta = (found[0][2].get("raw_json") or {}).get("chat") or {}
    kind = chat_meta.get("type") or rules.kind_of_chat(chat_id)
    rule = await rules.rule_for(owner_id, chat_id, kind, "userbot")
    if not rule.enabled:
        return  # чат выключили: нового не пишем и не уведомляем
    units = service.group_albums(found)
    for unit in units:
        # журнал и очистка истории — СРАЗУ: пачку уведомлений держим только в памяти
        await service.record_deleted(
            connection_id, chat_id, unit, bool(unit[0][1]["is_owner"])
        )
    # своих удалений не объявляем (очистка чата владельцем — обычное дело), но храним
    notifiable = [unit for unit in units if not unit[0][1]["is_owner"]]
    if rule.notify and notifiable:
        await burst.submit(owner_id, chat_id, notifiable, notices.flush_deleted)
