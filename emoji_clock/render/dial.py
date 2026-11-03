"""Циферблат: риски и стрелки для аналоговых часов.

Углы в градусах, 0° — вверх (на 12 часов), по часовой стрелке.
"""

import math

from emoji_clock.render.canvas import CX, CY, SS


def polar(angle, radius, cx=CX, cy=CY):
    """Точка на расстоянии radius (px) от центра под углом angle."""
    rad = math.radians(angle)
    return cx + radius * SS * math.sin(rad), cy - radius * SS * math.cos(rad)


def stroke(pen, p0, p1, width):
    """Линия с круглыми концами (width в px)."""
    w = width * SS
    pen.line([p0, p1], fill=255, width=int(round(w)))
    for x, y in (p0, p1):
        pen.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=255)


def ticks(pen, outer_radius, quarter=(9, 3.6), minor=(4.5, 2.4)):
    """12 рисок; (длина, толщина) для 12/3/6/9 и для остальных. outer_radius —
    где риска начинается снаружи, внутрь она идёт на свою длину."""
    for i in range(12):
        length, width = quarter if i % 3 == 0 else minor
        stroke(
            pen,
            polar(i * 30, outer_radius),
            polar(i * 30, outer_radius - length),
            width,
        )


def hands(pen, slot, minute_len, hour_len, minute_width, hour_width, hub):
    """Часовая и минутная стрелки + втулка. Часовая плавно движется с минутами."""
    hour, minute = int(slot[:2]) % 12, int(slot[3:5])
    center = (CX, CY)
    stroke(pen, center, polar(hour * 30 + minute * 0.5, hour_len), hour_width)
    stroke(pen, center, polar(minute * 6, minute_len), minute_width)
    r = hub * SS
    pen.ellipse([CX - r, CY - r, CX + r, CY + r], fill=255)
