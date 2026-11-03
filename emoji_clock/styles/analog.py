"""Analog: контурный циферблат с рисками и стрелками (часы и минуты).

Аналоговый стиль: 720 картинок вместо 1440 (13:05 рисуется как 01:05), поэтому
4 пака и вдвое быстрее загрузка.
"""

from emoji_clock.render import canvas, dial
from emoji_clock.style import ClockStyle

RADIUS, STROKE = 46, 3.6


def render(slot):
    mask = canvas.circle(RADIUS, stroke=STROKE)
    pen = canvas.draw(mask)
    dial.ticks(pen, RADIUS - STROKE - 1.2, quarter=(9, 3.6), minor=(4.5, 2.4))
    dial.hands(
        pen, slot, minute_len=31, hour_len=21, minute_width=3.8, hour_width=5.6, hub=4.8
    )
    return canvas.finish(mask)


STYLE = ClockStyle(
    id="analog",
    revision=1,
    titles={"ru": "Стрелки", "en": "Analog", "uk": "Стрілки"},
    render=render,
    hours=12,
    sample="10:10",
)
