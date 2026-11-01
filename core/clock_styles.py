"""Реестр стилей эмодзи-часов.

Чтобы добавить новый стиль:
  1. дописать ClockStyle в CLOCK_STYLES;
  2. добавить функцию рисования в scripts/emoji_clock_render.RENDERERS;
  3. python scripts/generate_emoji_images.py --style <id>
     python scripts/create_emoji_packs.py --style <id>
  Пока паки стиля не загружены полностью, API не даёт его выбрать, а у тех, кто
  успел выбрать, планировщик подставляет стиль по умолчанию.
"""

from dataclasses import dataclass

CLOCK_PACK_SIZE = 180
CLOCK_PACK_COUNT = 8  # 8 * 180 = 1440 минут в сутках


@dataclass(frozen=True)
class ClockStyle:
    id: str
    titles: dict  # locale -> название для интерфейса
    pack_prefix: str  # префикс имени набора в Telegram


CLOCK_STYLES = (
    ClockStyle(
        id="classic",
        titles={"ru": "Классика", "en": "Classic", "uk": "Класика"},
        # «clock0_by_<bot>» — так уже названы существующие паки, имена не меняем
        pack_prefix="clock",
    ),
    ClockStyle(
        id="stacked",
        titles={"ru": "Крупные цифры", "en": "Big digits", "uk": "Великі цифри"},
        pack_prefix="clock_stacked",
    ),
    ClockStyle(
        id="solid",
        titles={"ru": "Плитка", "en": "Tile", "uk": "Плитка"},
        pack_prefix="clock_solid",
    ),
)

DEFAULT_CLOCK_STYLE = CLOCK_STYLES[0].id
CLOCK_STYLE_IDS = tuple(style.id for style in CLOCK_STYLES)

_BY_ID = {style.id: style for style in CLOCK_STYLES}


def is_valid_clock_style(style_id):
    return style_id in _BY_ID


def normalize_clock_style(style_id):
    """Неизвестный/пустой стиль -> стиль по умолчанию."""
    return style_id if style_id in _BY_ID else DEFAULT_CLOCK_STYLE


def get_clock_style(style_id):
    return _BY_ID[normalize_clock_style(style_id)]


def clock_pack_name(style_id, pack_index, bot_username):
    prefix = get_clock_style(style_id).pack_prefix
    return f"{prefix}{pack_index}_by_{bot_username.lower()}"


def clock_pack_title(style_id, pack_index):
    title = get_clock_style(style_id).titles["en"]
    return f"Clock · {title} {pack_index + 1}/{CLOCK_PACK_COUNT}"
