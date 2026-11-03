"""Холст и маски.

Рисуем в 8-кратном разрешении (800x800) и в конце уменьшаем до 100x100 —
получаются гладкие края. Все размеры в функциях указываются в пикселях
итогового холста 100x100 (умножение на SS делается внутри).

Telegram перекрашивает эмодзи в цвет текста по альфа-каналу
(needs_repainting=True), поэтому рисуем «маски»: режим L, 255 = закрашено.
Итог — чёрный по прозрачному, альфа = маска.

Как Telegram выкладывает эмодзи в строку (замеры по скриншотам поля ввода и
шапки профиля): квадрат эмодзи центрируется по высоте ЗАГЛАВНЫХ букв, а
строчные оказываются ниже. Поэтому картинка занимает почти весь холст, а её
центр сдвинут вниз на VISUAL_CENTER_Y - 50 px.
"""

from PIL import Image, ImageChops, ImageDraw

CANVAS = 100  # Telegram: custom emoji ровно 100x100
SS = 8
BIG = CANVAS * SS

# Визуальный центр картинки по вертикали, px холста. 50 = центр холста.
# Если в Telegram эмодзи сидит выше/ниже строки — меняйте здесь (и повышайте
# revision у стилей, чтобы паки пересобрались).
VISUAL_CENTER_Y = 53.0

CX = BIG / 2
CY = VISUAL_CENTER_Y * SS


def blank():
    return Image.new("L", (BIG, BIG), 0)


def draw(mask):
    return ImageDraw.Draw(mask)


def union(*masks):
    result = masks[0]
    for mask in masks[1:]:
        result = ImageChops.lighter(result, mask)
    return result


def knockout(base, hole):
    """base с вырезанным по hole (вырезанное станет прозрачным)."""
    return ImageChops.multiply(base, ImageChops.invert(hole))


def rounded_rect(width, height, radius, stroke=None, cy=CY):
    """Скруглённый прямоугольник по центру; stroke=None — заливка, иначе рамка."""
    mask = blank()
    w, h = width * SS, height * SS
    box = [CX - w / 2, cy - h / 2, CX + w / 2, cy + h / 2]
    if stroke is None:
        draw(mask).rounded_rectangle(box, radius=radius * SS, fill=255)
    else:
        draw(mask).rounded_rectangle(
            box, radius=radius * SS, outline=255, width=int(round(stroke * SS))
        )
    return mask


def circle(radius, stroke=None, cy=CY):
    """Круг по центру; stroke=None — заливка, иначе кольцо."""
    mask = blank()
    r = radius * SS
    box = [CX - r, cy - r, CX + r, cy + r]
    if stroke is None:
        draw(mask).ellipse(box, fill=255)
    else:
        draw(mask).ellipse(box, outline=255, width=int(round(stroke * SS)))
    return mask


def finish(mask):
    """Маска -> готовая картинка 100x100 RGBA (чёрная, альфа = маска)."""
    image = Image.new("RGBA", mask.size, (0, 0, 0, 0))
    image.putalpha(mask)
    return image.resize((CANVAS, CANVAS), Image.LANCZOS)
