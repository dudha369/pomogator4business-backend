"""Solid: плитка-«иконка» с вырезанными цифрами, часы над минутами."""

from emoji_clock.render import canvas
from emoji_clock.render.text import BALOO, digits
from emoji_clock.style import ClockStyle

SIZE = 92


def render(slot):
    hh, mm = slot.split(":")
    tile = canvas.rounded_rect(SIZE, SIZE, radius=24)
    text = digits(BALOO, [hh, mm], box_w=SIZE - 20, box_h=SIZE - 22, gap_em=0.14)
    return canvas.finish(canvas.knockout(tile, text))


STYLE = ClockStyle(
    id="solid",
    revision=1,
    titles={"ru": "Плитка", "en": "Tile", "uk": "Плитка"},
    render=render,
)
