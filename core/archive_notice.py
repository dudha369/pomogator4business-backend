"""Тексты уведомлений архива: заголовок, «переслано от», тело, лимиты Telegram.

Чистые функции без обращений к Telegram — их легко тестировать."""

import html as _html
import re
from html import escape

from core.i18n import t

CAPTION_LIMIT = 1024  # подпись к медиа
MESSAGE_LIMIT = 4096  # обычное сообщение

# вложенные цитаты/код внутри нашей <blockquote> Telegram не принимает
_STRIPPED_ENTITIES = {"blockquote", "expandable_blockquote", "pre", "code"}

_TAGS = re.compile(r"<[^>]+>")

# Невидимый, но не «пустой» для Telegram символ (BRAILLE PATTERN BLANK): пустую цитату
# в «Было/Стало» отправить нельзя, а с этим символом она выглядит как пустая.
EMPTY = "\u2800"


def visible_len(markup: str) -> int:
    """Длина текста так, как её считает Telegram: без тегов, с раскрытыми &amp;."""
    return len(_html.unescape(_TAGS.sub("", markup)))


def render_text(text, entities) -> str:
    """Текст + entities -> HTML (с форматированием и премиум-эмодзи).

    Если отрисовать не удалось, возвращаем просто экранированный текст."""
    if not text:
        return ""
    if entities:
        try:
            from aiogram.types import MessageEntity
            from aiogram.utils.text_decorations import html_decoration

            items = [
                MessageEntity(**e)
                for e in entities
                if e.get("type") not in _STRIPPED_ENTITIES
            ]
            return html_decoration.unparse(text, items)
        except Exception:
            pass
    return escape(text)


def user_link(user_id, username) -> str | None:
    if username:
        return f"https://t.me/{username}"
    if user_id:
        return f"tg://user?id={user_id}"
    return None


def forward_link(forward) -> str | None:
    """Ссылка на источник пересылки, если она возможна."""
    if not forward:
        return None
    kind = forward.get("type")
    username = forward.get("username")
    if kind == "user":
        return user_link(forward.get("id"), username)
    if kind in ("chat", "channel") and username:
        message_id = forward.get("message_id")
        return f"https://t.me/{username}" + (f"/{message_id}" if message_id else "")
    return None


def format_forward(forward) -> str | None:
    """Откуда переслано -> HTML-фрагмент (со ссылкой, если она возможна)."""
    if not forward:
        return None
    label = escape(forward.get("name") or forward.get("signature") or "—")
    link = forward_link(forward)
    return f'<a href="{link}">{label}</a>' if link else label


def kind_detail(locale, snap) -> str:
    """Строки с описанием содержимого для типов, которые нельзя показать подписью."""
    kind = snap.get("kind")
    p = snap.get("payload") or {}
    label = t(f"archive.detail_{kind}", locale)
    if kind == "venue":
        lines = [label, escape(p.get("title") or ""), escape(p.get("address") or "")]
    elif kind == "location":
        lines = [label, f"{p.get('latitude')}, {p.get('longitude')}"]
    elif kind == "contact":
        name = " ".join(x for x in (p.get("first_name"), p.get("last_name")) if x)
        lines = [label, escape(f"{name} {p.get('phone_number') or ''}".strip())]
    elif kind == "poll":
        options = [f"• {escape(o.get('text', ''))}" for o in p.get("options") or []]
        lines = [label, escape(p.get("question") or "")] + options
    elif kind == "dice":
        lines = [f"{p.get('emoji') or '🎲'} {label}: {p.get('value')}"]
    else:
        lines = [label]
    return "\n".join(line for line in lines if line)


def build_notice(
    locale, mention, snap, *, limit, header_key="archive.deleted_header", detail=False
):
    """Готовый HTML уведомления: заголовок, «переслано от», описание, текст.

    Помещается в `limit` символов: если текст не влезает, он обрезается."""
    parts = [t(header_key, locale, mention=mention)]
    forwarded = format_forward(snap.get("forward"))
    if forwarded:
        parts.append(t("archive.forwarded_from", locale, source=forwarded))
    if detail:
        parts.append("\n" + kind_detail(locale, snap))
    head = "\n".join(parts)

    text = snap.get("text") or ""
    if not text:
        return head

    quote = "\n\n<blockquote expandable>{}</blockquote>"
    body = render_text(text, snap.get("entities"))
    overhead = 2  # перевод строк перед цитатой
    if visible_len(head) + overhead + visible_len(body) > limit:
        room = max(0, limit - visible_len(head) - overhead - 1)
        body = escape(text[:room]).rstrip() + "…"
    return head + quote.format(body)
