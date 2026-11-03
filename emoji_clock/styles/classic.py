"""Classic: рамка-«таблетка», время в одну строку (узкий шрифт Bebas Neue)."""

from emoji_clock.render import canvas
from emoji_clock.render.text import BEBAS, digits
from emoji_clock.style import ClockStyle

STROKE = 3.4
BADGE_W, BADGE_H = 97, 56
PAD_X, PAD_Y = 3.2, 4.0


def render(slot):
    frame = canvas.rounded_rect(BADGE_W, BADGE_H, radius=13, stroke=STROKE)
    text = digits(
        BEBAS,
        [slot],
        box_w=BADGE_W - 2 * (STROKE + PAD_X),
        box_h=BADGE_H - 2 * (STROKE + PAD_Y),
        max_stretch=1.3,
    )
    return canvas.finish(canvas.union(frame, text))


STYLE = ClockStyle(
    id="classic",
    revision=1,
    titles={"ru": "Классика", "en": "Classic", "uk": "Класика"},
    render=render,
)
