"""Проверка ссылок и файлов во входящих сообщениях: новых (шаг конвейера) и отредактированных."""

import asyncio
import hashlib
import logging

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest

from app.features.alerts.bot import report
from app.features.limits.bot import enforce
from app.features.linkscan import queries, service
from app.features.linkscan.local import (
    TRUSTED_HOSTS,
    assess_file,
    assess_link,
    extract_links,
)
from app.features.linkscan.providers import PROVIDERS
from app.features.linkscan.verdict import ALERT_LEVEL, NOTE
from app.platform.tasks import spawn
from config import settings
from db.models.connection import get_connection
from db.models.user_locale import get_locale

logger = logging.getLogger("bot.linkscan")
router = Router(name="linkscan")

MAX_FILE_BYTES = 20 * 1024 * 1024  # getFile в Bot API не отдаёт файлы больше
_DOWNLOADS = asyncio.Semaphore(3)  # скачивания идут параллельно, но не безгранично


async def linkscan_step(handler, message, data):
    """Новые сообщения (не владельца). Проверка идёт отдельной задачей и цепочку не держит."""
    inc = data["inc"]
    if not inc.is_owner:
        spawn(
            scan_message(inc.bot, inc.connection["owner_id"], message), name="linkscan"
        )
    return await handler(message, data)


async def edited_step(handler, message, data):
    """Правка тоже может принести ссылку или файл: подменить безобидное сообщение
    опасным после отправки — обычный приём. Обработчики архива не затрагиваем."""
    spawn(scan_edited(data["bot"], message), name="linkscan")
    return await handler(message, data)


router.edited_business_message.outer_middleware(edited_step)


async def scan_edited(bot, message) -> None:
    connection = await get_connection(message.business_connection_id)
    if connection and message.from_user.id != connection["owner_id"]:
        await scan_message(bot, connection["owner_id"], message)


async def _within_limit(owner_id: int, providers):
    """Внешние сервисы или (), если суточный лимит тарифа исчерпан: проверки внутри бота
    (без сети) продолжают работать. Считается один опрос внешних сервисов."""
    if not any(p.enabled() for p in providers):
        return providers
    return providers if await enforce(owner_id, "linkscan_checks_day") else ()


async def scan_message(bot, owner_id: int, message) -> None:
    cfg = await queries.get_settings(owner_id)
    if not cfg["enabled"]:
        return
    if cfg["scope"] == "selected" and message.chat.id not in cfg["chats"]:
        return
    providers = PROVIDERS if cfg["external"] else ()
    locale = await get_locale(owner_id)
    sender = getattr(message.from_user, "full_name", "") or ""
    ref = {
        "msg_id": str(message.message_id),
        "username": getattr(message.chat, "username", None) or "",
    }

    entities = getattr(message, "entities", None) or getattr(
        message, "caption_entities", None
    )
    text = message.text or getattr(message, "caption", None)
    for link in extract_links(text, entities, settings.LINKSCAN_MAX_LINKS):
        verdict = assess_link(link)
        if link.host not in TRUSTED_HOSTS:
            external = await _within_limit(owner_id, providers)
            verdict = await service.scan("url", link.url, verdict, external)
        if verdict.level >= ALERT_LEVEL:
            details = service.link_details(link, verdict, sender, ref, locale)
            await report(owner_id, f"{service.LINK_CODE}:{link.host[:48]}", **details)

    document = getattr(message, "document", None)
    if document is not None:
        await _scan_document(owner_id, bot, document, providers, sender, ref, locale)


class _Sha256:
    """Приёмник для `download_file`: файл считается по частям и нигде не хранится."""

    def __init__(self) -> None:
        self._hash = hashlib.sha256()

    def write(self, chunk: bytes) -> None:
        self._hash.update(chunk)

    def seek(self, _position: int) -> None:
        pass

    def hexdigest(self) -> str:
        return self._hash.hexdigest()


async def _sha256_of(bot, file_id: str) -> str | None:
    """sha256 файла или None, если Telegram его не отдаёт (больше 20 МБ)."""
    sink = _Sha256()
    try:
        async with _DOWNLOADS:
            file = await bot.get_file(file_id)
            await bot.download_file(file.file_path, destination=sink)
    except TelegramBadRequest:
        return None
    return sink.hexdigest()


async def _scan_document(owner_id, bot, document, providers, sender, ref, locale):
    """Любой документ, а не только «опасных» типов: тип влияет лишь на то, нужно ли
    второе мнение (VirusTotal)."""
    name = document.file_name or "file"
    unique = document.file_unique_id[:16]
    verdict = assess_file(name)
    sha256 = ""
    too_big = (document.file_size or 0) > MAX_FILE_BYTES
    if not too_big:  # слишком большой файл всё равно не скачать: лимит не тратим
        providers = await _within_limit(owner_id, providers)
    if any(p.enabled() for p in providers) and not too_big:
        sha256 = await _sha256_of(bot, document.file_id) or ""
        too_big = not sha256
        if sha256:
            verdict = await service.scan("file", sha256, verdict, providers)
    if verdict.level >= ALERT_LEVEL:
        details = service.file_details(name, sha256, verdict, sender, ref, locale)
        await report(owner_id, f"{service.FILE_CODE}:{unique}", **details)
    elif too_big and verdict.level >= NOTE:
        # по содержимому проверить нельзя: честно говорим об этом, а не молчим
        size_mb = (document.file_size or 0) // (1024 * 1024)
        details = service.unchecked_details(name, size_mb, verdict, sender, ref, locale)
        await report(owner_id, f"{service.UNCHECKED_CODE}:{unique}", **details)
