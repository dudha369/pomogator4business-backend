"""Rich Message (Bot API 10.1+) для уведомлений архива.

Зачем: в обычном сообщении у медиа одна подпись и она либо сверху, либо снизу,
альбом нельзя отправить с кнопкой, а «было/стало» — это три сообщения. В Rich
Message всё это одно сообщение: заголовок, подпись там, где она была, карусель
(<tg-slideshow>) для альбома и обычные inline-кнопки.

Мы пользуемся HTML-режимом: медиа подключаются по file_id через InputRichMessageMedia
и ссылки tg://photo?id=…, tg://video?id=…, tg://audio?id=….
Файлы, которые хранятся байтами (исчезающие), и документы в Rich не идут — для них
остаётся обычный способ отправки; решает вызывающий код."""

from html import escape

from aiogram.types import (
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaVoiceNote,
    InputRichMessage,
    InputRichMessageMedia,
)

from core.archive_notice import EMPTY, format_forward, render_text
from core.i18n import t

# что умеет Rich по file_id (документы, стикеры, кружки — нет)
VISUAL = ("photo", "video", "animation")
AUDIO = ("audio", "voice")
RICH_KINDS = VISUAL + AUDIO

_MAX_TEXT = 20000  # лимит Rich — 32768 символов на всё сообщение


def _media_object(kind, file_id):
    return {
        "photo": InputMediaPhoto,
        "video": InputMediaVideo,
        "animation": InputMediaAnimation,
        "audio": InputMediaAudio,
        "voice": InputMediaVoiceNote,
    }[kind](media=file_id)


def can_use_rich(snaps_entries) -> bool:
    """Все элементы — поддерживаемые типы с file_id и без хранимых байтов."""
    return bool(snaps_entries) and all(
        snap.get("kind") in RICH_KINDS
        and snap.get("file_id")
        and not (entry or {}).get("media_data")
        for snap, entry in snaps_entries
    )


def paragraphs(markup: str) -> str:
    """Строки заголовка -> абзацы (в HTML перевод строки сам по себе не работает)."""
    return "".join(f"<p>{line}</p>" for line in markup.split("\n") if line.strip())


def header_html(locale, mention, forward=None, header_key="archive.deleted_header"):
    html = paragraphs(t(header_key, locale, mention=mention))
    source = format_forward(forward)
    if source:
        html += paragraphs(t("archive.forwarded_from", locale, source=source))
    return html


def caption_html(snap) -> str:
    """Подпись/текст как цитата; пустой текст -> пустая строка."""
    text = (snap.get("text") or "")[:_MAX_TEXT]
    if not text:
        return ""
    if "\n" in text:
        # форматирование на нескольких строках склеить с абзацами нельзя — без него
        body = "".join(f"<p>{escape(line)}</p>" for line in text.split("\n") if line)
    else:
        body = render_text(text, snap.get("entities"))
    return f"<blockquote>{body}</blockquote>"


def quote_or_blank(text) -> str:
    """Цитата для «было/стало»; пусто -> невидимый символ, чтобы блок не исчез."""
    return caption_html({"text": text or EMPTY, "entities": None})


class RichBuilder:
    """Копит HTML и список медиа; id медиа выдаёт сам."""

    def __init__(self):
        self.parts: list[str] = []
        self.media: list[InputRichMessageMedia] = []

    def add_html(self, html: str):
        if html:
            self.parts.append(html)

    def _register(self, kind, file_id) -> str:
        media_id = f"m{len(self.media)}"
        self.media.append(
            InputRichMessageMedia(id=media_id, media=_media_object(kind, file_id))
        )
        return media_id

    def tag(self, snap) -> str:
        kind = snap["kind"]
        media_id = self._register(kind, snap["file_id"])
        spoiler = " tg-spoiler" if snap.get("has_spoiler") else ""
        if kind == "photo":
            return f'<img src="tg://photo?id={media_id}"{spoiler}/>'
        if kind in ("video", "animation"):
            return f'<video src="tg://video?id={media_id}"{spoiler}></video>'
        return f'<audio src="tg://audio?id={media_id}"></audio>'

    def add_media(self, snaps):
        """Один файл — как есть; несколько фото/видео — карусель."""
        tags = [self.tag(s) for s in snaps]
        visual = all(s["kind"] in VISUAL for s in snaps)
        if len(tags) > 1 and visual:
            self.add_html(f"<tg-slideshow>{''.join(tags)}</tg-slideshow>")
        else:
            for tag in tags:
                self.add_html(tag)

    def build(self) -> InputRichMessage:
        return InputRichMessage(
            html="".join(self.parts),
            media=self.media or None,
            skip_entity_detection=True,
        )


def caption_goes_above(snaps) -> bool:
    """Где держать подпись.

    Фото/видео/GIF — там же, где она была у собеседника (по умолчанию снизу).
    Голосовые и аудио в Rich читаются лучше, когда текст идёт перед файлом."""
    if all(s["kind"] in VISUAL for s in snaps):
        return any(s.get("show_caption_above") for s in snaps)
    return True


def build_deleted(locale, mention, snaps, forward=None) -> InputRichMessage:
    """Удалённое сообщение (или целый альбом) одним Rich Message."""
    builder = RichBuilder()
    builder.add_html(header_html(locale, mention, forward))
    caption = caption_html(next((s for s in snaps if s.get("text")), {}))
    above = caption_goes_above(snaps)
    if above:
        builder.add_html(caption)
    builder.add_media(snaps)
    if not above:
        builder.add_html(caption)
    return builder.build()


def build_edited_media(
    locale, mention, old, new, *, caption_changed, old_text, new_text
) -> InputRichMessage:
    """Заменено медиа: «Было» и «Стало» подписанными блоками."""
    builder = RichBuilder()
    builder.add_html(
        header_html(locale, mention, header_key="archive.edited_media_header")
    )
    for snap, label, text in (
        (old, "archive.caption_before", old_text),
        (new, "archive.caption_after", new_text),
    ):
        label_html = paragraphs(t(label, locale))
        builder.add_html(label_html)
        builder.add_html(builder.tag(snap))
        if caption_changed:
            builder.add_html(quote_or_blank(text))
    return builder.build()
