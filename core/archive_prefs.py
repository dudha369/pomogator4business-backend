"""Настройки оформления архива: что владелец выбрал у себя в веб-интерфейсе.

Значения по умолчанию берутся из config (ARCHIVE_*), поэтому до первого визита в
настройки бот ведёт себя как раньше. Настройки хранятся как JSON по подключению;
неизвестные ключи и неверные значения при чтении игнорируются, при записи — ошибка."""

import asyncio
from dataclasses import asdict, dataclass

from config import settings
from core import database as db

ALBUM_STYLES = ("slideshow", "collage", "list")
RICH_KINDS = ("photo", "video", "animation", "audio", "voice", "document")


@dataclass(frozen=True)
class ArchivePrefs:
    rich: bool = True  # уведомления Rich Message (иначе обычные сообщения)
    rich_kinds: tuple[str, ...] = ("photo", "video", "animation", "audio", "document")
    album_style: str = (
        "slideshow"  # slideshow — карусель, collage — плитка, list — подряд
    )
    collapse_media: bool = False  # вложения в сворачиваемый блок «Вложения: N»
    edit_history: bool = True  # правки одного сообщения — в одно уведомление
    caption_edit_media: bool = True  # файл над «Было/Стало» при правке подписи
    location_map: bool = False  # геолокацию показывать картой прямо в сообщении
    voice_transcript: bool = False  # распознавать голосовые и показывать текст

    def as_dict(self) -> dict:
        data = asdict(self)
        data["rich_kinds"] = list(self.rich_kinds)
        return data


def defaults() -> ArchivePrefs:
    """Значения по умолчанию: ARCHIVE_* из окружения поверх встроенных."""
    kinds = tuple(
        k.strip()
        for k in settings.ARCHIVE_RICH_KINDS.split(",")
        if k.strip() in RICH_KINDS
    )
    style = settings.ARCHIVE_ALBUM_STYLE
    return ArchivePrefs(
        rich=settings.ARCHIVE_RICH,
        rich_kinds=kinds,
        album_style=style if style in ALBUM_STYLES else "slideshow",
    )


def _clean(key, value):
    """Значение настройки или ValueError. Возвращает значение в нужном виде."""
    if key in (
        "rich",
        "collapse_media",
        "edit_history",
        "caption_edit_media",
        "location_map",
        "voice_transcript",
    ):
        if not isinstance(value, bool):
            raise ValueError(f"{key}: нужно true/false")
        return value
    if key == "album_style":
        if value not in ALBUM_STYLES:
            raise ValueError(f"album_style: одно из {ALBUM_STYLES}")
        return value
    if key == "rich_kinds":
        if not isinstance(value, (list, tuple)) or any(
            k not in RICH_KINDS for k in value
        ):
            raise ValueError(f"rich_kinds: список из {RICH_KINDS}")
        return tuple(k for k in RICH_KINDS if k in value)  # порядок и без повторов
    raise ValueError(f"неизвестная настройка: {key}")


def parse(data) -> ArchivePrefs:
    """Сохранённый JSON -> настройки (битые значения пропускаем)."""
    base = defaults()
    values = {}
    for key, value in (data or {}).items():
        try:
            values[key] = _clean(key, value)
        except ValueError:
            continue
    return ArchivePrefs(**{**asdict(base), **values})


def validate_patch(patch: dict) -> dict:
    """Частичное обновление из API -> очищенные значения (или ValueError)."""
    return {key: _clean(key, value) for key, value in patch.items()}


async def load_prefs(connection_id) -> ArchivePrefs:
    return parse(await db.get_archive_prefs_data(connection_id))


# «прочитать, изменить, записать» — не атомарная операция: два быстрых переключателя
# подряд иначе затёрли бы друг друга. Бот работает одним процессом, замка достаточно.
_update_lock = asyncio.Lock()


async def update_prefs(connection_id, patch: dict) -> ArchivePrefs:
    cleaned = validate_patch(patch)
    async with _update_lock:
        stored = dict(await db.get_archive_prefs_data(connection_id))
        stored.update(
            {k: list(v) if isinstance(v, tuple) else v for k, v in cleaned.items()}
        )
        await db.save_archive_prefs_data(connection_id, stored)
    return parse(stored)
