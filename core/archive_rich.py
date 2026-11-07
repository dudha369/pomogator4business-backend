"""Rich Message (Bot API 10.1+) для уведомлений архива — режим блоков.

Зачем: в обычном сообщении у медиа одна подпись, альбом нельзя отправить с кнопкой,
«было/стало» — это три сообщения, а историю правок некуда складывать. В Rich Message
это одно сообщение: заголовок, подпись там, где она была, карусель или коллаж для
альбома, документы, сворачиваемая история и обычные inline-кнопки.

Мы собираем сообщение блоками (InputRichBlock*), а не HTML: так работают документы
(в HTML для них нет разметки), медиа берутся по file_id без посредника, а текст
заголовков и подписей преобразуется из нашего HTML в RichText (core.rich_text).
Файлы, которые хранятся байтами (исчезающие), в Rich не идут — для них остаётся
обычная отправка; решает вызывающий код."""

from datetime import UTC, datetime
from html import escape

from aiogram.types import (
    InputMediaAnimation,
    InputMediaAudio,
    InputMediaDocument,
    InputMediaPhoto,
    InputMediaVideo,
    InputMediaVoiceNote,
    InputRichBlockAnimation,
    InputRichBlockAudio,
    InputRichBlockBlockQuotation,
    InputRichBlockCollage,
    InputRichBlockDetails,
    InputRichBlockDocument,
    InputRichBlockFooter,
    InputRichBlockMap,
    InputRichBlockParagraph,
    InputRichBlockPhoto,
    InputRichBlockSlideshow,
    InputRichBlockVideo,
    InputRichBlockVoiceNote,
    InputRichMessage,
    Location,
    RichBlockCaption,
)

from core.archive_notice import EMPTY, format_forward, render_text
from core.archive_prefs import ArchivePrefs, defaults
from core.i18n import t
from core.rich_text import html_to_rich

VISUAL = ("photo", "video", "animation")
ALL_KINDS = VISUAL + ("audio", "voice", "document")

_MAX_TEXT = 20000  # лимит Rich — 32768 символов на всё сообщение


def can_use_rich(snaps_entries, prefs: ArchivePrefs | None = None) -> bool:
    """Rich включён, все элементы — разрешённые типы с file_id и без хранимых байтов."""
    prefs = prefs or defaults()
    return (
        prefs.rich
        and bool(snaps_entries)
        and all(
            snap.get("kind") in prefs.rich_kinds
            and snap.get("file_id")
            and not (entry or {}).get("media_data")
            for snap, entry in snaps_entries
        )
    )


# ------------------------------ текстовые блоки -------------------------------


def paragraphs(markup: str) -> list:
    """Строки HTML -> абзацы (каждая строка — отдельный блок)."""
    return [
        InputRichBlockParagraph(text=html_to_rich(line))
        for line in markup.split("\n")
        if line.strip()
    ]


def header_blocks(locale, mention, forward=None, header_key="archive.deleted_header"):
    blocks = paragraphs(t(header_key, locale, mention=mention))
    source = format_forward(forward)
    if source:
        blocks += paragraphs(t("archive.forwarded_from", locale, source=source))
    return blocks


def quote_block(text, entities=None, *, html=None):
    """Цитата. html — уже готовая разметка (например, с подсветкой изменений);
    пустой текст -> невидимый символ, чтобы блок не исчез."""
    if html is None:
        text = (text or "")[:_MAX_TEXT]
        if not text:
            html = EMPTY
        elif "\n" in text:
            # форматирование на нескольких строках не склеить с абзацами — без него
            html = "\n".join(escape(line) for line in text.split("\n") if line)
        else:
            html = render_text(text, entities)
    return InputRichBlockBlockQuotation(blocks=paragraphs(html) or paragraphs(EMPTY))


def label_block(locale, key):
    return paragraphs(t(key, locale))


# --------------------------------- медиа --------------------------------------


def _caption(markup):
    return RichBlockCaption(text=html_to_rich(markup)) if markup else None


def media_block(snap, caption=None):
    """Один файл -> блок нужного типа (по file_id)."""
    kind, file_id = snap["kind"], snap["file_id"]
    spoiler = True if snap.get("has_spoiler") else None
    cap = _caption(caption)
    if kind == "photo":
        media = InputMediaPhoto(media=file_id, has_spoiler=spoiler)
        return InputRichBlockPhoto(photo=media, caption=cap)
    if kind == "video":
        media = InputMediaVideo(media=file_id, has_spoiler=spoiler)
        return InputRichBlockVideo(video=media, caption=cap)
    if kind == "animation":
        media = InputMediaAnimation(media=file_id, has_spoiler=spoiler)
        return InputRichBlockAnimation(animation=media, caption=cap)
    if kind == "audio":
        return InputRichBlockAudio(audio=InputMediaAudio(media=file_id), caption=cap)
    if kind == "voice":
        return InputRichBlockVoiceNote(
            voice_note=InputMediaVoiceNote(media=file_id), caption=cap
        )
    return InputRichBlockDocument(
        document=InputMediaDocument(media=file_id), caption=cap
    )


def details_block(summary_html, blocks, *, is_open=False):
    return InputRichBlockDetails(
        summary=html_to_rich(summary_html), blocks=blocks, is_open=is_open
    )


def media_blocks(locale, snaps, prefs: ArchivePrefs | None = None) -> list:
    """Файлы сообщения/альбома в блоки: карусель, плитка или подряд — как выбрал
    владелец; при collapse_media всё это лежит в сворачиваемом блоке."""
    prefs = prefs or defaults()
    blocks = [media_block(s) for s in snaps]
    if len(blocks) > 1 and all(s["kind"] in VISUAL for s in snaps):
        if prefs.album_style == "collage":
            blocks = [InputRichBlockCollage(blocks=blocks)]
        elif prefs.album_style == "slideshow":
            blocks = [InputRichBlockSlideshow(blocks=blocks)]
    if prefs.collapse_media:
        summary = t("archive.collapsed_media", locale, count=len(snaps))
        return [details_block(summary, blocks)]
    return blocks


def transcript_block(locale, text):
    """Расшифровка голосового — сворачиваемый блок."""
    return details_block(t("archive.transcript", locale), paragraphs(escape(text)))


def caption_goes_above(snaps) -> bool:
    """Где держать подпись.

    Фото/видео/GIF — там же, где она была у собеседника (по умолчанию снизу).
    Для аудио, файлов и голосовых текст идёт перед файлом."""
    if all(s["kind"] in VISUAL for s in snaps):
        return any(s.get("show_caption_above") for s in snaps)
    return True


# ------------------------------- сообщения ------------------------------------


def _message(blocks) -> InputRichMessage:
    return InputRichMessage(blocks=blocks, skip_entity_detection=True)


def build_deleted(
    locale, mention, snaps, forward=None, prefs: ArchivePrefs | None = None
) -> InputRichMessage:
    """Удалённое сообщение (или целый альбом) одним Rich Message."""
    blocks = header_blocks(locale, mention, forward)
    text_snap = next((s for s in snaps if s.get("text")), None)
    caption = (
        [quote_block(text_snap["text"], text_snap.get("entities"))] if text_snap else []
    )
    media = media_blocks(locale, snaps, prefs)
    if caption_goes_above(snaps):
        blocks += caption + media
    else:
        blocks += media + caption
    transcript = next((s["transcript"] for s in snaps if s.get("transcript")), None)
    if transcript:
        blocks.append(transcript_block(locale, transcript))
    return _message(blocks)


def build_location(
    locale, mention, snap, forward=None, prefs: ArchivePrefs | None = None
) -> InputRichMessage:
    """Геолокация/место картой прямо в сообщении."""
    payload = snap.get("payload") or {}
    point = payload.get("location") or payload
    blocks = header_blocks(locale, mention, forward)
    if snap["kind"] == "venue":
        blocks += paragraphs(
            "\n".join(
                f"<b>{escape(v)}</b>" if i == 0 else escape(v)
                for i, v in enumerate(
                    v for v in (payload.get("title"), payload.get("address")) if v
                )
            )
        )
    blocks.append(
        InputRichBlockMap(
            location=Location(latitude=point["latitude"], longitude=point["longitude"]),
            zoom=15,
        )
    )
    return _message(blocks)


def build_edited_media(
    locale, mention, old, new, *, caption_changed, old_text, new_text
) -> InputRichMessage:
    """Заменено медиа: «Было:» и «Стало:» с файлами (и подписями, если менялись)."""
    blocks = header_blocks(locale, mention, header_key="archive.edited_media_header")
    for snap, label, text in (
        (old, "archive.caption_before", old_text),
        (new, "archive.caption_after", new_text),
    ):
        blocks += label_block(locale, label)
        blocks.append(media_block(snap))
        if caption_changed:
            blocks.append(quote_block(text))
    return _message(blocks)


def _time_html(timestamp) -> str:
    """Время в часовом поясе того, кто читает (клиент подставит сам)."""
    if not timestamp:
        return ""
    fallback = datetime.fromtimestamp(int(timestamp), tz=UTC).strftime("%d.%m %H:%M")
    return f'<tg-time unix="{int(timestamp)}" format="dt">{fallback}</tg-time>'


def build_edit_history(
    locale,
    mention,
    versions,
    times,
    *,
    current_html,
    header_key,
    media_snaps=(),
    prefs: ArchivePrefs | None = None,
) -> InputRichMessage:
    """Вся история правок одного сообщения одним Rich Message.

    versions — тексты от первоначального до текущего, times — время каждой версии
    (None, если неизвестно). Сверху «Было/Стало» для последней правки, ранние версии
    свёрнуты в раскрывающийся блок."""
    blocks = header_blocks(locale, mention, header_key=header_key)
    if media_snaps:
        blocks += media_blocks(locale, list(media_snaps), prefs)
    blocks += label_block(locale, "archive.caption_before")
    blocks.append(quote_block(versions[-2]))
    blocks += label_block(locale, "archive.caption_after")
    blocks.append(quote_block(None, html=current_html))

    earlier = list(zip(versions[:-2], times[:-2], strict=False))
    if earlier:
        inner = []
        for text, stamp in earlier:
            when = _time_html(stamp)
            if when:
                inner += paragraphs(when)
            inner.append(quote_block(text))
        blocks.append(
            InputRichBlockDetails(
                summary=html_to_rich(
                    t("archive.history_earlier", locale, count=len(earlier))
                ),
                blocks=inner,
            )
        )
    blocks.append(
        InputRichBlockFooter(
            text=html_to_rich(t("archive.edits_count", locale, count=len(versions) - 1))
        )
    )
    return _message(blocks)
