"""Disc digits: залитый круг с вырезанными цифрами (часы над минутами)."""

from emoji_clock.render import canvas
from emoji_clock.render.text import BALOO, digits
from emoji_clock.style import ClockStyle

RADIUS = 46


def render(slot):
    hh, mm = slot.split(":")
    disc = canvas.circle(RADIUS)
    text = digits(BALOO, [hh, mm], box_w=54, box_h=60, gap_em=0.14)
    return canvas.finish(canvas.knockout(disc, text))


STYLE = ClockStyle(
    id="disc_digits",
    revision=1,
    titles={"ru": "Диск", "en": "Disc", "uk": "Диск"},
    render=render,
)
