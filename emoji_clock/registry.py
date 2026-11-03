"""Реестр стилей. Чтобы добавить стиль: файл в emoji_clock/styles/ + строка здесь."""

from emoji_clock.style import ClockStyle
from emoji_clock.styles import (
    analog,
    analog_disc,
    classic,
    disc_digits,
    ring_digits,
    solid,
    stacked,
)

# Порядок = порядок в мини-приложении. Первый — стиль по умолчанию.
STYLES = (
    classic.STYLE,
    stacked.STYLE,
    solid.STYLE,
    ring_digits.STYLE,
    disc_digits.STYLE,
    analog.STYLE,
    analog_disc.STYLE,
)

STYLE_IDS = tuple(style.id for style in STYLES)
DEFAULT_STYLE_ID = STYLES[0].id

_BY_ID = {style.id: style for style in STYLES}
assert len(_BY_ID) == len(STYLES), "id стилей должны быть уникальны"


def is_valid_style_id(style_id):
    return style_id in _BY_ID


def normalize_style_id(style_id):
    """Неизвестный/пустой id -> стиль по умолчанию."""
    return style_id if style_id in _BY_ID else DEFAULT_STYLE_ID


def get_style(style_id) -> ClockStyle:
    return _BY_ID[normalize_style_id(style_id)]
