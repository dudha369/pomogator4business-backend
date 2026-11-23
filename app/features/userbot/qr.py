"""QR для входа: PNG для бота и data-URI для мини-приложения."""

import base64
import io

import qrcode


def render_png(text: str) -> bytes:
    buffer = io.BytesIO()
    qrcode.make(text, border=2).save(buffer, format="PNG")
    return buffer.getvalue()


def render_data_uri(text: str) -> str:
    return "data:image/png;base64," + base64.b64encode(render_png(text)).decode()
