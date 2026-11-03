"""Часы в эмодзи-статусе: стили, рендер картинок и синхронизация паков Telegram.

emoji_clock.registry   — какие стили есть
emoji_clock.styles.*   — по одному файлу на стиль
emoji_clock.render.*   — общие кирпичики рисования
emoji_clock.sync.*     — паки в Telegram (используется scripts/clock_sync.py)
"""

from emoji_clock.registry import (
    DEFAULT_STYLE_ID,
    STYLE_IDS,
    STYLES,
    get_style,
    is_valid_style_id,
    normalize_style_id,
)
from emoji_clock.style import CLOCK_PACK_SIZE, ClockStyle, all_time_keys, pack_revision

__all__ = [
    "CLOCK_PACK_SIZE",
    "DEFAULT_STYLE_ID",
    "STYLES",
    "STYLE_IDS",
    "ClockStyle",
    "all_time_keys",
    "get_style",
    "is_valid_style_id",
    "normalize_style_id",
    "pack_revision",
]
