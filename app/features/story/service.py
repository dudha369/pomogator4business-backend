import io

from PIL import Image, ImageFilter

GRID = {
    3: (3, 1),
    6: (3, 2),
    9: (3, 3),
}

_TILE_W = 1080
_TILE_H = 1920
_BLUR_RADIUS = 40


def _blur_letterbox(cell: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Вписывает cell в target_w x target_h БЕЗ обрезки содержимого — а
    пустые поля заполняет размытой растянутой версией той же cell, а не
    сплошным цветом (так делают Instagram/TikTok для контента не того
    соотношения сторон). Именно так должен выглядеть каждый тайл, чтобы
    при просмотре подряд мозаика собралась в исходное фото без потерь по
    краям."""
    cell_w, cell_h = cell.size

    # Размытый фон на весь канвас — "cover" (с запасом, лишнее обрезаем).
    bg_scale = max(target_w / cell_w, target_h / cell_h)
    bg = cell.resize(
        (round(cell_w * bg_scale), round(cell_h * bg_scale)), Image.LANCZOS
    )
    bg_left = (bg.width - target_w) // 2
    bg_top = (bg.height - target_h) // 2
    bg = bg.crop((bg_left, bg_top, bg_left + target_w, bg_top + target_h))
    bg = bg.filter(ImageFilter.GaussianBlur(_BLUR_RADIUS))

    # Резкий передний план — "contain" (без обрезки содержимого).
    fg_scale = min(target_w / cell_w, target_h / cell_h)
    fg = cell.resize(
        (round(cell_w * fg_scale), round(cell_h * fg_scale)), Image.LANCZOS
    )

    canvas = bg
    paste_x = (target_w - fg.width) // 2
    paste_y = (target_h - fg.height) // 2
    canvas.paste(fg, (paste_x, paste_y))
    return canvas


def split_image(image_bytes, parts):
    """Режет ИСХОДНОЕ фото на сетку rows x cols "как есть" (без потери
    содержимого), затем каждую получившуюся ячейку вписывает в 1080x1920
    через _blur_letterbox. Порядок тайлов — слева направо, сверху вниз.
    """
    rows, cols = GRID[parts]
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    src_w, src_h = image.size
    cell_w = src_w // cols
    cell_h = src_h // rows

    tiles = []
    for row in range(rows):
        for col in range(cols):
            box = (
                col * cell_w,
                row * cell_h,
                src_w if col == cols - 1 else (col + 1) * cell_w,
                src_h if row == rows - 1 else (row + 1) * cell_h,
            )
            cell = image.crop(box)
            tile = _blur_letterbox(cell, _TILE_W, _TILE_H)
            buffer = io.BytesIO()
            tile.save(buffer, format="JPEG", quality=95)
            tiles.append(buffer.getvalue())
    return tiles
