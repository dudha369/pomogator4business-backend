"""Analog disc: залитый диск, риски и стрелки вырезаны (лучше всех в мелком размере)."""

from emoji_clock.render import canvas, dial
from emoji_clock.style import ClockStyle

RADIUS = 46


def render(slot):
    disc = canvas.circle(RADIUS)
    hole = canvas.blank()
    pen = canvas.draw(hole)
    dial.ticks(pen, RADIUS - 4.2, quarter=(8, 3.8), minor=(4.2, 2.6))
    dial.hands(
        pen, slot, minute_len=29, hour_len=19.5, minute_width=4.2, hour_width=6.2, hub=5
    )
    return canvas.finish(canvas.knockout(disc, hole))


STYLE = ClockStyle(
    id="analog_disc",
    revision=1,
    titles={"ru": "Стрелки на диске", "en": "Analog disc", "uk": "Стрілки на диску"},
    render=render,
    hours=12,
    sample="10:10",
)
