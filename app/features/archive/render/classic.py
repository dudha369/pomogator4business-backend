"""Тексты уведомлений архива: заголовок, «переслано от», тело, лимиты Telegram.

Чистые функции без обращений к Telegram — их легко тестировать."""

import asyncio
import html as _html
import itertools
import re
from difflib import SequenceMatcher
from html import escape

from app.platform.i18n import t

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

            # aiogram кладёт url в href как есть: `&` в адресе надо экранировать
            items = [
                MessageEntity(**{**e, "url": escape(e["url"])} if e.get("url") else e)
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


_DIE_FACES = "⚀⚁⚂⚃⚄⚅"
_SLOT_SYMBOLS = ("BAR", "🍇", "🍋", "7️⃣")
_SLOT_TRIPLES = {1, 22, 43, 64}  # три одинаковых символа


def describe_dice(locale, emoji, value) -> str:
    """Бросок -> понятный результат (кубик не перебросить, поэтому рассказываем)."""
    emoji = emoji or "🎲"
    value = int(value or 0)
    if emoji == "🎰":
        n = value - 1
        reels = " ".join(_SLOT_SYMBOLS[d] for d in (n % 4, (n // 4) % 4, n // 16))
        verdict = ""
        if value == 64:
            verdict = " " + t("archive.dice_jackpot", locale)
        elif value in _SLOT_TRIPLES:
            verdict = " " + t("archive.dice_triple", locale)
        return f"🎰 [{reels}]{verdict}"
    if emoji == "🏀":
        key = "archive.dice_hit" if value >= 4 else "archive.dice_miss"
        return f"🏀 {t(key, locale)}"
    if emoji == "⚽":
        key = "archive.dice_goal" if value >= 3 else "archive.dice_miss"
        return f"⚽ {t(key, locale)}"
    if emoji in ("🎯", "🎳"):
        if value == 6:
            key = "archive.dice_bullseye" if emoji == "🎯" else "archive.dice_strike"
            return f"{emoji} {t(key, locale)}"
        if value == 1:
            return f"{emoji} {t('archive.dice_miss', locale)}"
        return f"{emoji} {t('archive.dice_of', locale, value=value, max=6)}"
    face = _DIE_FACES[value - 1] if 1 <= value <= 6 else "🎲"
    return f"{face} {t('archive.dice_rolled', locale)}: {value}"


def _gift_lines(locale, snap):
    kind = snap.get("kind")
    p = snap.get("payload") or {}
    gift = p.get("gift") or {}
    lines = [t(f"archive.detail_{kind}", locale)]
    if kind == "unique_gift":
        title = f"{gift.get('base_name') or gift.get('name') or ''} #{gift.get('number') or ''}"
        lines.append(f"<b>{escape(title.strip())}</b>")
        for part in ("model", "symbol", "backdrop"):
            name = (gift.get(part) or {}).get("name")
            if name:
                lines.append(escape(name))
    elif gift.get("star_count"):
        lines.append(f"⭐ {gift['star_count']}")
    if p.get("text"):
        lines.append(escape(p["text"]))
    return lines


def kind_detail(locale, snap) -> str:
    """Описание содержимого для типов, которые не показать подписью (HTML)."""
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
        lines = [label, escape(p.get("question") or ""), *options]
    elif kind == "dice":
        lines = [f"<b>{describe_dice(locale, p.get('emoji'), p.get('value'))}</b>"]
    elif kind in ("gift", "unique_gift"):
        lines = _gift_lines(locale, snap)
        lines[0] = f"<b>{lines[0]}</b>"
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
    head = "\n".join(parts)
    if detail:
        head += f"\n\n<blockquote>{kind_detail(locale, snap)}</blockquote>"

    text = snap.get("text") or ""
    transcript = snap.get("transcript") or ""
    result = head
    if text:
        quote = "\n\n<blockquote expandable>{}</blockquote>"
        body = render_text(text, snap.get("entities"))
        overhead = 2  # перевод строк перед цитатой
        if visible_len(head) + overhead + visible_len(body) > limit:
            room = max(0, limit - visible_len(head) - overhead - 1)
            body = escape(text[:room]).rstrip() + "…"
        result = head + quote.format(body)
    if transcript:
        label = t("archive.transcript", locale)
        room = limit - visible_len(result) - visible_len(label) - 6
        if room > 20:  # расшифровка идёт после подписи и урезается первой
            body = escape(transcript)
            if len(transcript) > room:
                body = escape(transcript[:room]).rstrip() + "…"
            result += f"\n\n<b>{label}</b>\n<blockquote expandable>{body}</blockquote>"
    return result


# --- «Было/Стало» ------------------------------------------------------------

_CLIP = 1700  # два текста по 4096 не влезут в одно сообщение — режем оба
# поверх этих сущностей жирное выделение не накладываем: у премиум-эмодзи вместо
# текста плейсхолдер, а внутри уже жирного оно ничего не меняет
_NO_HIGHLIGHT = {"custom_emoji", "bold"}


def u16_len(text: str) -> int:
    """Длина в UTF-16: в таких единицах Telegram считает offset/length сущностей."""
    return len(text.encode("utf-16-le")) // 2


def clip_text(text, entities=None, limit: int = _CLIP):
    """Обрезает текст и сущности согласованно -> (текст, сущности).

    Сущность, вылезшая за край, укорачивается; премиум-эмодзи, которое пришлось бы
    резать, отбрасывается целиком (половина эмодзи не рисуется)."""
    text = text or ""
    if len(text) <= limit:
        return text, entities
    cut = text[:limit].rstrip()
    end = u16_len(cut)
    kept = []
    for entity in entities or ():
        offset, length = entity["offset"], entity["length"]
        if offset >= end:
            continue
        if offset + length > end:
            if entity.get("type") == "custom_emoji":
                continue
            entity = {**entity, "length": end - offset}
        kept.append(entity)
    return cut + "…", kept or None


def clip(text) -> str:
    return clip_text(text)[0]


def changed_ranges(old_text: str, new_text: str) -> list[tuple[int, int]]:
    """Вставленное/изменённое в new_text: диапазоны [start, end) в единицах UTF-16.

    Сравниваем по символам Python (эмодзи не рвутся пополам), а границы переводим в
    UTF-16 — именно так считаются offset сущностей Telegram."""
    position = [0]
    for char in new_text:
        position.append(position[-1] + (2 if ord(char) > 0xFFFF else 1))
    matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)
    return [
        (position[j1], position[j2])
        for tag, _i1, _i2, j1, j2 in matcher.get_opcodes()
        if tag in ("replace", "insert") and j2 > j1
    ]


def _subtract(span, blocked):
    parts = [span]
    for b_start, b_end in blocked:
        rest = []
        for start, end in parts:
            if b_end <= start or b_start >= end:
                rest.append((start, end))
                continue
            if start < b_start:
                rest.append((start, b_start))
            if b_end < end:
                rest.append((b_end, end))
        parts = rest
    return parts


def bold_entities(ranges, entities) -> list[dict]:
    """Жирное выделение для диапазонов так, чтобы оно НЕ пересекалось с сущностями
    сообщения: каждый кусок целиком внутри или целиком снаружи любой сущности — иначе
    HTML получится с перехлёстом тегов."""
    blocked = [
        (e["offset"], e["offset"] + e["length"])
        for e in entities
        if e.get("type") in _NO_HIGHLIGHT
    ]
    cuts = sorted(
        {p for e in entities for p in (e["offset"], e["offset"] + e["length"])}
    )
    result = []
    for span in ranges:
        for start, end in _subtract(span, blocked):
            points = [start, *(c for c in cuts if start < c < end), end]
            result += [
                {"type": "bold", "offset": a, "length": b - a}
                for a, b in itertools.pairwise(points)
            ]
    return result


def highlight_changes(old_text: str, new_text: str, new_entities=None) -> str:
    """Новый текст в HTML: форматирование сообщения сохранено, вставленное/изменённое
    дополнительно выделено жирным."""
    entities = [
        e for e in (new_entities or ()) if e.get("type") not in _STRIPPED_ENTITIES
    ]
    extra = bold_entities(changed_ranges(old_text, new_text), entities)
    return render_text(new_text, [*entities, *extra])


async def highlight_changes_async(
    old_text: str, new_text: str, new_entities=None
) -> str:
    """SequenceMatcher квадратичен: на патологичных строках до секунд — в поток,
    иначе встаёт весь event loop (WEB_CONCURRENCY=1)."""
    return await asyncio.to_thread(highlight_changes, old_text, new_text, new_entities)


async def highlight_edit(old_text, old_entities, new_text, new_entities) -> str:
    """Единое место «обрезать оба текста и подсветить правку» для обеих веток."""
    old_text, _ = clip_text(old_text, old_entities)
    new_text, new_entities = clip_text(new_text, new_entities)
    return await highlight_changes_async(old_text, new_text, new_entities)


async def before_after(
    locale, old_text, new_text, old_entities=None, new_entities=None
) -> str:
    old_html = render_text(*clip_text(old_text, old_entities)) or EMPTY
    new_html = (
        await highlight_edit(old_text, old_entities, new_text, new_entities)
        if new_text
        else EMPTY
    )
    return (
        f"\n\n{t('archive.caption_before', locale)}\n"
        f"<blockquote expandable>{old_html}</blockquote>\n\n"
        f"{t('archive.caption_after', locale)}\n"
        f"<blockquote expandable>{new_html}</blockquote>"
    )
