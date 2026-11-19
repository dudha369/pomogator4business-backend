"""Проверка parse_mode у исходящих текстов — общая для всех тестов.

Telegram не разбирает HTML без parse_mode: теги показываются текстом. Обратно, при
parse_mode=html любой неэкранированный `<` или `&` отклоняет весь запрос. Ошибки
отправки код часто гасит (log_suppressed), поэтому guard не бросает исключение на
месте, а копит нарушения — их проверяет autouse-фикстура после каждого теста."""

import re

_TAGS = "b|i|u|s|em|strong|a|code|pre|tg-emoji|tg-spoiler|blockquote|tg-time"
# настоящая HTML-разметка бота
_TAG = re.compile(rf"</?(?:{_TAGS})(?:\s[^<>]*)?>", re.IGNORECASE)
# `<` не из нашей разметки (в html-режиме Telegram такой текст отклонит)
_BAD_LT = re.compile(rf"<(?!/?(?:{_TAGS})(?:[\s>]))")
# голый `&` — не начало сущности
_BAD_AMP = re.compile(r"&(?!(?:lt|gt|amp|quot|#\d+|#x[0-9a-f]+);)", re.IGNORECASE)
_ENTITY = re.compile(r"&(?:lt|gt|amp|quot);")

FIELDS = ("text", "caption")


def _mode(value):
    """parse_mode → 'html' / 'markdown' / None (нет, в т.ч. aiogram UNSET)."""
    return value if isinstance(value, str) and value else None


def problems(method: str, kwargs: dict) -> list[str]:
    """Нарушения одного вызова Bot API (пустой список — всё в порядке)."""
    mode = _mode(kwargs.get("parse_mode"))
    has_entities = bool(kwargs.get("entities") or kwargs.get("caption_entities"))
    found = []
    for field in FIELDS:
        value = kwargs.get(field)
        if not isinstance(value, str) or has_entities:
            continue
        if mode is None and (_TAG.search(value) or _ENTITY.search(value)):
            found.append(f"{method}.{field} без parse_mode, но с HTML: {value[:80]!r}")
        elif (
            mode
            and mode.lower() == "html"
            and (_BAD_LT.search(value) or _BAD_AMP.search(value))
        ):
            found.append(f"{method}.{field}: не экранирован `<`/`&`: {value[:80]!r}")
    return found
