import io

from PIL import Image, ImageDraw, ImageFont, ImageOps

_SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
_SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"


def load_font(size, serif=False):
    path = _SERIF_BOLD if serif else _SANS_BOLD
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def draw_outlined_text(
    draw,
    position,
    text,
    font,
    fill="white",
    outline="black",
    outline_width=3,
    anchor=None,
):
    x, y = position
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def wrap_text(draw, text, font, max_width):
    words = text.split()
    if not words:
        return []

    lines = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def to_sepia(image):
    grayscale = ImageOps.grayscale(image)
    sepia_image = ImageOps.colorize(grayscale, black="#3a2a1a", white="#d9c8a5")
    return sepia_image.convert("RGB")


def circular_crop(image, size):
    image = ImageOps.fit(image, (size, size), method=Image.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)
    result = Image.new("RGBA", (size, size))
    result.paste(image, (0, 0), mask)
    return result


def to_bytes(image, fmt="JPEG"):
    buffer = io.BytesIO()
    if fmt == "JPEG" and image.mode in ("RGBA", "P"):
        image = image.convert("RGB")
    image.save(buffer, format=fmt)
    return buffer.getvalue()
