"""Превью стилей без Telegram и БД: контрольный лист и PNG для мини-приложения."""

import os

from PIL import Image, ImageDraw, ImageFont

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Шрифты только для превью (на сами эмодзи не влияют): жирный гротеск с кириллицей.
_FONT_CANDIDATES = [
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/tahomabd.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/Library/Fonts/Arial Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
]
CAP_HEIGHT = 36  # px: высота заглавных в поле ввода Telegram (замер по скриншоту)
EMOJI_SIZE = 70  # px: сторона квадрата эмодзи там же
SMALL_SIZES = (22, 30)


def _font():
    """(шрифт, умеет_ли_кириллицу). Размер подбирается по высоте заглавных,
    поэтому превью в масштабе Telegram не зависит от найденного шрифта."""
    candidates = [(p, True) for p in _FONT_CANDIDATES] + [
        (os.path.join(_ROOT, "assets", "fonts", "Baloo2-Bold.ttf"), False)
    ]
    for path, cyrillic in candidates:
        if not os.path.exists(path):
            continue
        try:
            probe = ImageFont.truetype(path, 100)
            _, top, _, bottom = probe.getbbox("A", anchor="ls")
            size = 100 * CAP_HEIGHT / (bottom - top)
            return ImageFont.truetype(path, int(round(size))), cyrillic
        except OSError:
            continue
    return ImageFont.load_default(size=50), False


def _tinted(image, color):
    tinted = Image.new("RGBA", image.size, color)
    tinted.putalpha(image.getchannel("A"))
    return tinted


def _line(style, dark):
    """Эмодзи в строке текста в масштабе поля ввода Telegram: центр квадрата
    эмодзи = центр заглавных (замер по скриншоту)."""
    bg = (28, 28, 30, 255) if dark else (255, 255, 255, 255)
    fg = (255, 255, 255, 255) if dark else (0, 0, 0, 255)
    font, cyrillic = _font()
    words = ("aaa", "AAA", "дудха" if cyrillic else "dudha")

    sheet = Image.new("RGBA", (520, 120), bg)
    pen = ImageDraw.Draw(sheet)
    base = 86
    x = 8

    def word(text):
        nonlocal x
        pen.text((x, base), text, font=font, fill=fg, anchor="ls")
        x += int(font.getlength(text)) + 8

    word(words[0])
    emoji = style.render(style.sample).resize((EMOJI_SIZE, EMOJI_SIZE), Image.LANCZOS)
    sheet.alpha_composite(
        _tinted(emoji, fg), (x, int(base - CAP_HEIGHT / 2 - EMOJI_SIZE / 2))
    )
    x += EMOJI_SIZE + 8
    word(words[1])
    word(words[2])
    return sheet


def contact_sheet(styles):
    """Каждый стиль в строке текста (светлая и тёмная тема) и в мелких размерах."""
    row = 120
    width = 520 * 2 + len(SMALL_SIZES) * 2 * 70
    sheet = Image.new("RGBA", (width, row * len(styles)), (255, 255, 255, 255))
    pen = ImageDraw.Draw(sheet)
    for i, style in enumerate(styles):
        y = i * row
        sheet.alpha_composite(_line(style, dark=False), (0, y))
        sheet.alpha_composite(_line(style, dark=True), (520, y))
        icon = style.render(style.sample)
        x = 1040
        for dark in (False, True):
            bg = (28, 28, 30, 255) if dark else (255, 255, 255, 255)
            fg = (255, 255, 255, 255) if dark else (0, 0, 0, 255)
            for size in SMALL_SIZES:
                cell = Image.new("RGBA", (70, row), bg)
                cell.alpha_composite(
                    _tinted(icon.resize((size, size), Image.LANCZOS), fg),
                    (35 - size // 2, 60 - size // 2),
                )
                sheet.alpha_composite(cell, (x, y))
                x += 70
        pen.text((6, y + 102), style.id, fill=(130, 130, 130, 255))
    return sheet.convert("RGB")


def save_contact_sheet(styles, path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    contact_sheet(styles).save(path)


def export_samples(styles, directory):
    """По PNG на стиль (<id>.png) — превью для выбора стиля в мини-приложении."""
    os.makedirs(directory, exist_ok=True)
    paths = []
    for style in styles:
        path = os.path.join(directory, f"{style.id}.png")
        style.render(style.sample).save(path, optimize=True)
        paths.append(path)
    return paths
