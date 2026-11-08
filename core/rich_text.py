"""Наш HTML (заголовки из локалей, текст с форматированием) -> RichText для Rich Message.

В режиме блоков текст описывается объектами RichText, а не HTML. Заголовки уведомлений
и пользовательский текст у нас уже готовы как Telegram-HTML (<b>, <a>, <tg-emoji>…),
поэтому здесь один небольшой преобразователь, а не вторая система разметки."""

from html.parser import HTMLParser

from aiogram.types import (
    RichTextBold,
    RichTextCode,
    RichTextCustomEmoji,
    RichTextDateTime,
    RichTextItalic,
    RichTextMarked,
    RichTextSpoiler,
    RichTextStrikethrough,
    RichTextUnderline,
    RichTextUrl,
)

_SIMPLE = {
    "b": RichTextBold,
    "strong": RichTextBold,
    "i": RichTextItalic,
    "em": RichTextItalic,
    "u": RichTextUnderline,
    "ins": RichTextUnderline,
    "s": RichTextStrikethrough,
    "strike": RichTextStrikethrough,
    "del": RichTextStrikethrough,
    "code": RichTextCode,
    "mark": RichTextMarked,
    "tg-spoiler": RichTextSpoiler,
}


def _compact(children):
    if not children:
        return ""
    if len(children) == 1:
        return children[0]
    return children


def _wrap(tag, attrs, children):
    inner = _compact(children)
    if tag in _SIMPLE:
        return _SIMPLE[tag](text=inner)
    if tag == "span" and "tg-spoiler" in (attrs.get("class") or ""):
        return RichTextSpoiler(text=inner)
    if tag == "a" and attrs.get("href"):
        return RichTextUrl(text=inner, url=attrs["href"])
    if tag == "tg-emoji" and attrs.get("emoji-id"):
        fallback = inner if isinstance(inner, str) and inner else "🙂"
        return RichTextCustomEmoji(
            custom_emoji_id=attrs["emoji-id"], alternative_text=fallback
        )
    if tag == "tg-time" and attrs.get("unix"):
        return RichTextDateTime(
            text=inner,
            unix_time=int(attrs["unix"]),
            date_time_format=attrs.get("format") or "dt",
        )
    return children  # неизвестный тег: оставляем содержимое как есть


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = [(None, {}, [])]

    def _add(self, node):
        if isinstance(node, list):
            self.stack[-1][2].extend(node)
        elif node != "":
            self.stack[-1][2].append(node)

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self._add("\n")
            return
        self.stack.append((tag, dict(attrs), []))

    def handle_startendtag(self, tag, attrs):
        if tag == "br":
            self._add("\n")
        else:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index][0] == tag:
                break
        else:
            return
        while len(self.stack) > index:
            name, attrs, children = self.stack.pop()
            self._add(_wrap(name, attrs, children))

    def handle_data(self, data):
        self._add(data)


def html_to_rich(markup: str):
    """'<b>Привет</b>, <a href="…">мир</a>' -> RichText (строка, список или объект)."""
    parser = _Parser()
    parser.feed(markup)
    parser.close()
    while len(parser.stack) > 1:  # незакрытые теги закрываем сами
        name, attrs, children = parser.stack.pop()
        parser._add(_wrap(name, attrs, children))
    return _compact(parser.stack[0][2])
