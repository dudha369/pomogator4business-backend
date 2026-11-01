"""Генерация PNG для эмодзи-паков с часами (по всем стилям или по одному).

Запуск (из корня проекта):

    python scripts/generate_emoji_images.py                 # все стили
    python scripts/generate_emoji_images.py --style solid   # один стиль

Результат:
  * assets/generated_emoji/<style>/pack_N/HH-MM.png — 1440 картинок 100x100 на стиль;
  * assets/generated_emoji/preview.png — контрольный лист: каждый стиль рядом с
    текстом (как в поле ввода Telegram), на светлой/тёмной теме и в 24px.
    Посмотрите его ДО загрузки/замены паков;
  * скрипт проверяет, что вертикальное положение бейджа у всех 1440 картинок
    стиля одинаково.

Положение относительно строки текста настраивается в одном месте:
scripts/emoji_clock_render.py -> VISUAL_CENTER_Y.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw, ImageFont

from core.clock_styles import (
    CLOCK_PACK_COUNT,
    CLOCK_PACK_SIZE,
    CLOCK_STYLE_IDS,
)
from scripts import emoji_clock_render as renderer

OUTPUT_DIR = "assets/generated_emoji"

PREVIEW_TIMES = ["00:00", "08:47", "12:34", "21:00", "23:59"]
_DEJAVU_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def all_time_keys():
    return [f"{h:02d}:{m:02d}" for h in range(24) for m in range(60)]


def style_dir(style):
    return os.path.join(OUTPUT_DIR, style)


def _ink_vertical_center(image):
    bbox = image.getchannel("A").point(lambda a: 255 if a > 127 else 0).getbbox()
    return (bbox[1] + bbox[3]) / 2


def _tinted(image, color):
    tinted = Image.new("RGBA", image.size, color)
    tinted.putalpha(image.getchannel("A"))
    return tinted


def _line_mock(style, time_text, dark):
    """Эмодзи в строке текста в масштабе поля ввода Telegram: квадрат эмодзи 70px,
    высота заглавных 36px, центр квадрата = центр заглавных (замер по скриншоту)."""
    bg = (28, 28, 30, 255) if dark else (255, 255, 255, 255)
    fg = (255, 255, 255, 255) if dark else (0, 0, 0, 255)
    canvas = Image.new("RGBA", (520, 130), bg)
    draw = ImageDraw.Draw(canvas)
    try:
        font = ImageFont.truetype(_DEJAVU_BOLD, 50)
    except OSError:
        font = ImageFont.load_default()
    base, cap_h, size = 92, 36, 70
    cap_center = base - cap_h / 2
    x = 8
    for text in ("aaa",):
        draw.text((x, base), text, font=font, fill=fg, anchor="ls")
        x += int(font.getlength(text)) + 6
    emoji = renderer.render_clock_emoji(time_text, style).resize(
        (size, size), Image.LANCZOS
    )
    canvas.alpha_composite(_tinted(emoji, fg), (x, int(cap_center - size / 2)))
    x += size + 6
    for text in ("AAA", "дудха"):
        draw.text((x, base), text, font=font, fill=fg, anchor="ls")
        x += int(font.getlength(text)) + 8
    return canvas


def _make_preview(styles, path):
    row_h = 135
    sheet = Image.new("RGBA", (1040, row_h * len(styles)), (255, 255, 255, 255))
    for i, style in enumerate(styles):
        y = i * row_h
        sheet.alpha_composite(_line_mock(style, "21:00", dark=False), (0, y))
        sheet.alpha_composite(_line_mock(style, "21:00", dark=True), (520, y))
        label = ImageDraw.Draw(sheet)
        label.text((8, y + 112), style, fill=(120, 120, 120, 255))
    sheet.convert("RGB").save(path)

    strip = Image.new(
        "RGBA", (len(PREVIEW_TIMES) * 110, 110 * len(styles)), (255, 255, 255, 255)
    )
    for r, style in enumerate(styles):
        for c, t in enumerate(PREVIEW_TIMES):
            strip.alpha_composite(
                renderer.render_clock_emoji(t, style), (c * 110 + 5, r * 110 + 5)
            )
    strip.convert("RGB").save(path.replace("preview.png", "preview_full_size.png"))


def generate_style(style):
    times = all_time_keys()
    assert len(times) == CLOCK_PACK_SIZE * CLOCK_PACK_COUNT

    centers = []
    for pack_index in range(CLOCK_PACK_COUNT):
        pack_dir = os.path.join(style_dir(style), f"pack_{pack_index}")
        os.makedirs(pack_dir, exist_ok=True)
        chunk = times[pack_index * CLOCK_PACK_SIZE : (pack_index + 1) * CLOCK_PACK_SIZE]
        for time_key in chunk:
            image = renderer.render_clock_emoji(time_key, style)
            assert image.size == (100, 100) and image.mode == "RGBA"
            centers.append(_ink_vertical_center(image))
            image.save(
                os.path.join(pack_dir, f"{time_key.replace(':', '-')}.png"),
                optimize=True,
            )

    spread = max(centers) - min(centers)
    print(
        f"[{style}] {len(times)} картинок -> {style_dir(style)}/ "
        f"(вертикальный центр {min(centers):.2f}..{max(centers):.2f}px)"
    )
    if spread > 1.0:
        print(f"[{style}] ВНИМАНИЕ: разброс {spread:.2f}px — проверьте рендер")


def main():
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").strip().split("\n")[0] or None
    )
    parser.add_argument("--style", choices=[*CLOCK_STYLE_IDS, "all"], default="all")
    args = parser.parse_args()

    styles = list(CLOCK_STYLE_IDS) if args.style == "all" else [args.style]
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for style in styles:
        generate_style(style)

    preview = os.path.join(OUTPUT_DIR, "preview.png")
    _make_preview(styles, preview)
    print(f"Контрольный лист: {preview}")


if __name__ == "__main__":
    main()
