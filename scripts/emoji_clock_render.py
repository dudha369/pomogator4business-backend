import io

from PIL import Image, ImageChops, ImageDraw, ImageFont

CANVAS = 100
SS = 8

VISUAL_CENTER_Y = 53.0

_BALOO = ("assets/fonts/Baloo2-Bold.ttf", 800)
_BEBAS = ("assets/fonts/BebasNeue-Regular.ttf", None)

_DIGITS = "0123456789"
_INK = (0, 0, 0, 255)


class _Face:
    def __init__(self, spec, tracking_em, embolden_em):
        self.path, self.weight = spec
        self.tracking = tracking_em
        self.embolden = embolden_em
        font = self.font(1000)
        sw = int(round(embolden_em * 1000))
        tops, bottoms, widths = [], [], []
        for ch in _DIGITS:
            l, t, r, b = font.getbbox(ch, anchor="ls", stroke_width=sw)
            tops.append(t)
            bottoms.append(b)
            widths.append(r - l)
        self.top = min(tops) / 1000  # < 0: выше базовой линии
        self.h = (max(bottoms) - min(tops)) / 1000
        self.digit_cell = max(widths) / 1000 + tracking_em
        l, _, r, _ = font.getbbox(":", anchor="ls", stroke_width=sw)
        self.colon_cell = (r - l) / 1000 + 2 * tracking_em

    def font(self, size):
        f = ImageFont.truetype(self.path, max(1, int(round(size))))
        if self.weight is not None:
            try:
                f.set_variation_by_axes([self.weight])
            except Exception:
                pass
        return f

    def line_em(self, line):
        w = sum(self.colon_cell if c == ":" else self.digit_cell for c in line)
        return w - self.tracking  # у последнего символа трекинг не нужен


_FACES = {}


def _face(spec, tracking_em=0.05, embolden_em=0.0):
    key = (spec, tracking_em, embolden_em)
    if key not in _FACES:
        _FACES[key] = _Face(spec, tracking_em, embolden_em)
    return _FACES[key]


def _text_layer(face, lines, size, gap_em):
    font = face.font(size)
    sw = int(round(face.embolden * size))
    line_h = face.h * size
    gap = gap_em * size
    widths = [face.line_em(line) * size for line in lines]
    width = max(widths)
    height = line_h * len(lines) + gap * (len(lines) - 1)
    layer = Image.new("RGBA", (int(round(width)) + 2, int(round(height)) + 2))
    draw = ImageDraw.Draw(layer)
    y = 1.0
    for line, line_w in zip(lines, widths):
        x = 1.0 + (width - line_w) / 2
        baseline = y - face.top * size
        for ch in line:
            cell = (face.colon_cell if ch == ":" else face.digit_cell) * size
            l, _, r, _ = font.getbbox(ch, anchor="ls", stroke_width=sw)
            pad = face.tracking * size / 2 if ch != ":" else face.tracking * size
            cx = x + pad + (cell - 2 * pad) / 2
            draw.text(
                (cx - (l + r) / 2, baseline),
                ch,
                font=font,
                fill=_INK,
                anchor="ls",
                stroke_width=sw,
                stroke_fill=_INK,
            )
            x += cell
        y += line_h + gap
    return layer


def _fit_text(face, lines, box_w, box_h, gap_em=0.0, max_stretch=1.0):
    width_em = max(face.line_em(line) for line in lines)
    height_em = face.h * len(lines) + gap_em * (len(lines) - 1)
    size = box_w / width_em
    stretch = 1.0
    if height_em * size < box_h:
        stretch = min(max_stretch, box_h / (height_em * size))
    else:
        size = min(size, box_h / height_em)
    layer = _text_layer(face, lines, size, gap_em)
    if stretch != 1.0:
        layer = layer.resize(
            (layer.width, int(round(layer.height * stretch))), Image.LANCZOS
        )
    return layer


def _center(canvas_size, layer, cy):
    return (
        int(round((canvas_size - layer.width) / 2)),
        int(round(cy - layer.height / 2)),
    )


def _validate(time_text):
    digits = time_text.replace(":", "")
    if len(time_text) != 5 or time_text[2] != ":" or not digits.isdigit():
        raise ValueError(f"Ожидается формат HH:MM, получено {time_text!r}")


def _render_classic(time_text):
    s = SS
    big = CANVAS * s
    cy = VISUAL_CENTER_Y * s
    face = _face(_BEBAS, 0.05, embolden_em=0.028)

    stroke, radius = 3.4 * s, 13 * s
    badge_w, badge_h = 97 * s, 56 * s
    left, top = (big - badge_w) / 2, cy - badge_h / 2

    canvas = Image.new("RGBA", (big, big))
    ImageDraw.Draw(canvas).rounded_rectangle(
        [left, top, left + badge_w, top + badge_h],
        radius=radius,
        outline=_INK,
        width=int(round(stroke)),
    )
    inner_w = badge_w - 2 * (stroke + 3.2 * s)
    inner_h = badge_h - 2 * (stroke + 4.0 * s)
    layer = _fit_text(face, [time_text], inner_w, inner_h, max_stretch=1.3)
    canvas.alpha_composite(layer, _center(big, layer, cy))
    return canvas


def _render_stacked(time_text):
    s = SS
    big = CANVAS * s
    cy = VISUAL_CENTER_Y * s
    face = _face(_BALOO, 0.04)
    hh, mm = time_text.split(":")

    layer = _fit_text(face, [hh, mm], 96 * s, 92 * s, gap_em=0.13)
    canvas = Image.new("RGBA", (big, big))
    canvas.alpha_composite(layer, _center(big, layer, cy))
    return canvas


def _render_solid(time_text):
    s = SS
    big = CANVAS * s
    cy = VISUAL_CENTER_Y * s
    face = _face(_BALOO, 0.04)
    hh, mm = time_text.split(":")

    tile_w = tile_h = 92 * s
    left, top = (big - tile_w) / 2, cy - tile_h / 2
    tile = Image.new("L", (big, big), 0)
    ImageDraw.Draw(tile).rounded_rectangle(
        [left, top, left + tile_w, top + tile_h], radius=24 * s, fill=255
    )

    layer = _fit_text(
        face, [hh, mm], tile_w - 2 * 10 * s, tile_h - 2 * 11 * s, gap_em=0.14
    )
    mask = Image.new("L", (big, big), 0)
    mask.paste(layer.getchannel("A"), _center(big, layer, cy))

    alpha = ImageChops.multiply(tile, ImageChops.invert(mask))
    canvas = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    canvas.putalpha(alpha)
    return canvas


RENDERERS = {
    "classic": _render_classic,
    "stacked": _render_stacked,
    "solid": _render_solid,
}


def render_clock_emoji(time_text, style="classic"):
    _validate(time_text)
    try:
        renderer = RENDERERS[style]
    except KeyError:
        raise ValueError(f"Неизвестный стиль {style!r}, доступно: {list(RENDERERS)}")
    return renderer(time_text).resize((CANVAS, CANVAS), Image.LANCZOS)


def render_to_bytes(time_text, style="classic"):
    buffer = io.BytesIO()
    render_clock_emoji(time_text, style).save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
