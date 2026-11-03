"""Ring digits: кольцо, внутри время цифрами (часы над минутами)."""

from emoji_clock.render import canvas
from emoji_clock.render.text import BALOO, digits
from emoji_clock.style import ClockStyle

RADIUS, STROKE = 46, 3.6


def render(slot):
    hh, mm = slot.split(":")
    ring = canvas.circle(RADIUS, stroke=STROKE)
    text = digits(BALOO, [hh, mm], box_w=52, box_h=62, gap_em=0.13)
    return canvas.finish(canvas.union(ring, text))


STYLE = ClockStyle(
    id="ring_digits",
    revision=1,
    titles={"ru": "Кольцо", "en": "Ring", "uk": "Кільце"},
    render=render,
)
