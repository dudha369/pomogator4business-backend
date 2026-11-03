"""Цифры для часов.

Два правила, из-за которых время не «плавает» и не кривится:
  1. Цифры стоят в ТАБЛИЧНЫХ ячейках одной ширины (у «1» и «0» ширина в шрифте
     разная, из-за этого раньше строка «11:11» выглядела иначе, чем «20:08»).
  2. Каждая строка центрируется по РЕАЛЬНЫМ краям чернил, а не по ширине
     ячеек, иначе пара цифр съезжает вправо на полтрекинга (было до 2 px).
Высота цифр одна для всех: берётся максимум по глифам 0-9 (с овершутами).
"""

import os
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from emoji_clock.render import canvas
from emoji_clock.render.canvas import BIG, CX, CY, SS

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_REF = 1000  # кегль, на котором снимаются метрики
_DIGITS = "0123456789"


class Face:
    """Шрифт + метрики цифр в em (не зависят от конкретного времени)."""

    def __init__(self, file, weight=None, tracking_em=0.05, embolden_em=0.0):
        self.path = os.path.join(_ROOT, "assets", "fonts", file)
        self.weight = weight  # для variable-шрифтов (ось Weight)
        self.tracking = tracking_em  # зазор между цифрами
        self.embolden = embolden_em  # «утяжеление» контуром, в долях кегля
        self._metrics = None

    def font(self, size):
        font = ImageFont.truetype(self.path, max(1, int(round(size))))
        if self.weight is not None:
            try:
                font.set_variation_by_axes([self.weight])
            except Exception:
                pass
        return font

    @lru_cache(maxsize=None)
    def ink_em(self, ch):
        """Настоящие края чернил символа (left, top, right, bottom) в em
        относительно точки отрисовки (anchor 'ls'). Измеряется по пикселям:
        getbbox в Pillow даёт границы по ширине шага символа, а не по чернилам,
        из-за чего «1» и «7» центровались неточно."""
        font = self.font(_REF)
        sw = int(round(self.embolden * _REF))
        origin_x, origin_y = _REF // 2, int(_REF * 1.4)
        probe = Image.new("L", (_REF * 2, _REF * 2), 0)
        ImageDraw.Draw(probe).text(
            (origin_x, origin_y),
            ch,
            font=font,
            fill=255,
            anchor="ls",
            stroke_width=sw,
            stroke_fill=255,
        )
        left, top, right, bottom = probe.getbbox()
        return (
            (left - origin_x) / _REF,
            (top - origin_y) / _REF,
            (right - origin_x) / _REF,
            (bottom - origin_y) / _REF,
        )

    def _load(self):
        if self._metrics is None:
            digits = [self.ink_em(ch) for ch in _DIGITS]
            colon = self.ink_em(":")
            self._metrics = {
                "top": min(d[1] for d in digits),  # < 0: выше базовой линии
                "height": max(d[3] for d in digits) - min(d[1] for d in digits),
                "digit_cell": max(d[2] - d[0] for d in digits) + self.tracking,
                "colon_cell": (colon[2] - colon[0]) + 2 * self.tracking,
            }
        return self._metrics

    top = property(lambda self: self._load()["top"])
    height = property(lambda self: self._load()["height"])
    digit_cell = property(lambda self: self._load()["digit_cell"])
    colon_cell = property(lambda self: self._load()["colon_cell"])

    def cell(self, ch):
        return self.colon_cell if ch == ":" else self.digit_cell

    def glyph_ink_em(self, ch):
        """(левый, правый) край чернил символа в em."""
        left, _, right, _ = self.ink_em(ch)
        return left, right

    def line_ink_em(self, line):
        """Ширина чернил строки в em (от левого края первой до правого края последней)."""
        cells = [self.cell(ch) for ch in line]
        first_l, first_r = self.glyph_ink_em(line[0])
        last_l, last_r = self.glyph_ink_em(line[-1])
        first_center = cells[0] / 2
        last_center = sum(cells[:-1]) + cells[-1] / 2
        return (last_center + (last_r - last_l) / 2) - (
            first_center - (first_r - first_l) / 2
        )


# Baloo 2 Bold — округлые цифры (stacked, solid, круги)
BALOO = Face("Baloo2-Bold.ttf", weight=800, tracking_em=0.04)
# Bebas Neue — узкие цифры, чтобы время в одну строку получилось высоким
BEBAS = Face("BebasNeue-Regular.ttf", tracking_em=0.05, embolden_em=0.028)


def _layer(face, lines, size, gap_em):
    """Альфа-слой с текстом (по высоте — ровно чернила, по ширине — ровно чернила
    самой широкой строки; каждая строка центрирована по своим чернилам)."""
    font = face.font(size)
    sw = int(round(face.embolden * size))
    line_h = face.height * size
    gap = gap_em * size

    placed = []
    for line in lines:
        x = 0.0
        items = []
        for ch in line:
            cell = face.cell(ch) * size
            left, right = (v * size for v in face.glyph_ink_em(ch))
            items.append((ch, x + cell / 2, left, right))
            x += cell
        ink_l = items[0][1] - (items[0][3] - items[0][2]) / 2
        ink_r = items[-1][1] + (items[-1][3] - items[-1][2]) / 2
        placed.append((items, ink_l, ink_r))

    width = max(ink_r - ink_l for _, ink_l, ink_r in placed)
    height = line_h * len(lines) + gap * (len(lines) - 1)
    layer = Image.new("RGBA", (int(round(width)) + 2, int(round(height)) + 2))
    pen = ImageDraw.Draw(layer)

    y = 1.0
    for items, ink_l, ink_r in placed:
        shift = 1.0 + (width - (ink_r - ink_l)) / 2 - ink_l
        baseline = y - face.top * size
        for ch, center, left, right in items:
            pen.text(
                (shift + center - (left + right) / 2, baseline),
                ch,
                font=font,
                fill=(0, 0, 0, 255),
                anchor="ls",
                stroke_width=sw,
                stroke_fill=(0, 0, 0, 255),
            )
        y += line_h + gap
    return layer


def digits(face, lines, box_w, box_h, gap_em=0.0, max_stretch=1.0, cy=CY):
    """Маска с текстом, вписанным в рамку box_w x box_h (px) и центрированным.

    lines — строки текста ('21:00' или ['21', '00']). max_stretch > 1 разрешает
    растянуть цифры по вертикали, если по высоте остаётся место (имитация более
    узкого шрифта)."""
    box_w, box_h = box_w * SS, box_h * SS
    width_em = max(face.line_ink_em(line) for line in lines)
    height_em = face.height * len(lines) + gap_em * (len(lines) - 1)

    size = box_w / width_em
    stretch = 1.0
    if height_em * size < box_h:
        stretch = min(max_stretch, box_h / (height_em * size))
    else:
        size = box_h / height_em

    layer = _layer(face, lines, size, gap_em)
    if stretch != 1.0:
        layer = layer.resize(
            (layer.width, int(round(layer.height * stretch))), Image.LANCZOS
        )

    mask = canvas.blank()
    mask.paste(
        layer.getchannel("A"),
        (int(round(CX - layer.width / 2)), int(round(cy - layer.height / 2))),
    )
    return mask
