"""Stacked: без рамки, крупные цифры, часы над минутами."""

from emoji_clock.render import canvas
from emoji_clock.render.text import BALOO, digits
from emoji_clock.style import ClockStyle


def render(slot):
    hh, mm = slot.split(":")
    return canvas.finish(digits(BALOO, [hh, mm], box_w=96, box_h=92, gap_em=0.13))


STYLE = ClockStyle(
    id="stacked",
    revision=1,
    titles={"ru": "Крупные цифры", "en": "Big digits", "uk": "Великі цифри"},
    render=render,
)
