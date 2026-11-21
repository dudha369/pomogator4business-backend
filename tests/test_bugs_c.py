"""Регрессии чата «Баги C» (HANDOFF_audit, задача 14).

(а) сообщения самого бота попадают в историю; (б) «Было/Стало» не теряет сущности."""

import html as html_lib
import random
import re
from html.parser import HTMLParser

import pytest
from aiogram.methods import EditMessageText, SendChatAction, SendMediaGroup, SendMessage
from aiogram.types import MessageEntity

import bot_instance
from app.features.archive.bot.deleted import on_business_deleted
from app.features.archive.bot.edited import on_business_edited
from app.features.archive.render.classic import (
    before_after,
    changed_ranges,
    clip_text,
    highlight_changes,
)
from app.features.archive.render.rich_text import split_html_lines
from app.features.history.models import MessageHistory
from app.features.history.outgoing import OutgoingRecorder
from app.features.history.service import get_history_entry
from app.platform.telegram.self_actions import delete_own_messages
from config import settings
from db.models.module_settings import disable_module
from tests import html_guard
from tests.conftest import on_business_message

from .conftest import CONNECTION_ID, OWNER_ID, deleted_event, make_message

CHAT = 7


# ------------------------------ (а) исходящие ---------------------------------


@pytest.fixture
async def ready(connection, api_bot, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", False)
    await disable_module(CONNECTION_ID, "scam")
    return connection


async def send_via_session(method, result):
    """Прогоняет «ответ Telegram» через настоящий middleware сессии бота."""

    async def make_request(bot, m):
        return result

    return await OutgoingRecorder()(make_request, bot_instance.bot, method)


def business_send(text="⏳ таймер", **kwargs):
    return SendMessage(
        business_connection_id=CONNECTION_ID, chat_id=CHAT, text=text, **kwargs
    )


async def test_recorder_is_installed_on_main_bot():
    middlewares = bot_instance.bot.session.middleware._middlewares
    assert any(isinstance(m, OutgoingRecorder) for m in middlewares)


async def test_bot_message_goes_to_history_as_owner(connection):
    sent = make_message("⏳ таймер", chat_id=CHAT, from_id=OWNER_ID)
    assert await send_via_session(business_send(), sent) is sent

    entry = await get_history_entry(CONNECTION_ID, CHAT, sent.message_id)
    assert entry["is_owner"] is True and entry["text"] == "⏳ таймер"
    assert entry["kind"] == "text"


async def test_no_duplicate_when_telegram_also_sends_update(connection):
    await disable_module(CONNECTION_ID, "scam")
    bot = None
    sent = make_message("дубль", chat_id=CHAT, from_id=OWNER_ID)
    await send_via_session(business_send("дубль"), sent)
    await send_via_session(business_send("дубль"), sent)
    from tests.conftest import FakeBot

    bot = FakeBot()
    await on_business_message(sent, bot)  # тот же message_id пришёл апдейтом
    rows = await MessageHistory.filter(chat_id=CHAT, message_id=sent.message_id)
    assert len(rows) == 1


async def test_bot_edits_and_foreign_methods_are_not_recorded(connection):
    edit = make_message("правка", chat_id=CHAT, from_id=OWNER_ID)
    await send_via_session(
        EditMessageText(
            business_connection_id=CONNECTION_ID,
            chat_id=CHAT,
            message_id=edit.message_id,
            text="правка",
        ),
        edit,
    )
    plain = make_message("не бизнес", chat_id=CHAT, from_id=OWNER_ID)
    await send_via_session(SendMessage(chat_id=CHAT, text="не бизнес"), plain)
    typing = SendChatAction(
        business_connection_id=CONNECTION_ID, chat_id=CHAT, action="typing"
    )
    assert await send_via_session(typing, True) is True
    assert await MessageHistory.all().count() == 0


async def test_media_group_records_every_message(connection):
    group = [
        make_message(caption=f"к{i}", chat_id=CHAT, from_id=OWNER_ID) for i in (1, 2)
    ]
    method = SendMediaGroup(
        business_connection_id=CONNECTION_ID, chat_id=CHAT, media=[]
    )
    assert await send_via_session(method, group) == group
    assert await MessageHistory.all().count() == 2


async def test_failed_recording_never_breaks_sending(connection, monkeypatch):
    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("app.features.history.outgoing.save_history", boom)
    sent = make_message("ok", chat_id=CHAT, from_id=OWNER_ID)
    assert await send_via_session(business_send("ok"), sent) is sent


async def test_deleted_bot_message_is_shown_in_archive(ready, bot):
    sent = make_message("секретный таймер", chat_id=CHAT, from_id=OWNER_ID)
    await send_via_session(business_send("секретный таймер"), sent)

    await on_business_deleted(deleted_event(CHAT, [sent.message_id]), bot)
    (notice,) = bot.sent
    assert "секретный таймер" in notice["text"]


async def test_deletion_made_by_bot_itself_stays_silent_and_cleans_history(ready, bot):
    sent = make_message("исчезни", chat_id=CHAT, from_id=OWNER_ID)
    await send_via_session(business_send("исчезни"), sent)

    assert await delete_own_messages(bot, CONNECTION_ID, CHAT, [sent.message_id])
    await on_business_deleted(deleted_event(CHAT, [sent.message_id]), bot)
    assert bot.sent == []
    assert await get_history_entry(CONNECTION_ID, CHAT, sent.message_id) is None


# ----------------------- (б) UTF-16, обрезка, подсветка ------------------------


def ent(kind, offset, length, **extra):
    return {"type": kind, "offset": offset, "length": length, **extra}


def test_changed_ranges_are_utf16_not_python_indices():
    # 🙂 — один символ Python, но две единицы UTF-16
    assert changed_ranges("a🙂b", "a🙂Xb") == [(3, 4)]
    assert changed_ranges("ab", "aXb") == [(1, 2)]
    assert changed_ranges("abc", "ab") == []  # удаление в новом тексте не видно


def test_highlight_keeps_custom_emoji_and_does_not_bold_it():
    new = "ab🙂c"
    out = highlight_changes(
        "ab🙂", new, [ent("custom_emoji", 2, 2, custom_emoji_id="77")]
    )
    assert '<tg-emoji emoji-id="77">🙂</tg-emoji>' in out
    assert out.endswith("<b>c</b>") and "<b>🙂" not in out


def test_highlight_keeps_link_and_splits_bold_at_entity_borders():
    out = highlight_changes(
        "see now",
        "see site now",
        [ent("text_link", 4, 4, url="https://x.y/?a=1&b=2")],
    )
    assert '<a href="https://x.y/?a=1&amp;b=2">' in out
    assert_well_formed(out, "see site now")
    assert "<b>" in out


def test_highlight_does_not_double_bold_existing_bold():
    out = highlight_changes("a", "a<b>", [ent("bold", 0, 4)])
    assert out.count("<b>") == 1  # родное жирное, без вложенного


def test_stripped_entities_do_not_leak_into_highlight():
    out = highlight_changes("x", "x code", [ent("code", 2, 4), ent("pre", 0, 6)])
    assert "<code>" not in out and "<pre>" not in out


def test_clip_text_cuts_entities_consistently_in_utf16():
    text = "🙂" * 1000 + "x" * 900  # 1900 символов, но в UTF-16 — 2900 единиц
    entities = [
        ent("bold", 0, 2000),  # пересекает границу: укорачивается
        ent("italic", 100, 10),  # целиком до границы: не меняется
        ent("custom_emoji", 3398, 2, custom_emoji_id="1"),  # за границей
        ent("custom_emoji", 3398, 2, custom_emoji_id="2"),
    ]
    cut, kept = clip_text(text, entities, limit=1700)
    assert cut.endswith("…") and len(cut) == 1701
    end = 2 * 1000 + 700  # граница в UTF-16 (1000 эмодзи + 700 «x»)
    assert kept[0] == ent("bold", 0, 2000) or kept[0]["length"] <= end
    assert all(e["offset"] + e["length"] <= end for e in kept)
    assert ent("italic", 100, 10) in kept
    assert not [e for e in kept if e["type"] == "custom_emoji"]


def test_clip_text_drops_emoji_that_would_be_cut_in_half():
    # премиум-эмодзи из нескольких символов (ZWJ-последовательность, 5 единиц UTF-16)
    family = "👨\u200d👩"
    text = "x" * 1698 + family + "y" * 10
    entities = [ent("custom_emoji", 1698, 5, custom_emoji_id="9")]
    cut, kept = clip_text(text, entities, 1700)
    assert kept is None and cut.endswith("…")


def test_clip_text_is_noop_for_short_text():
    entities = [ent("bold", 0, 3)]
    assert clip_text("abc", entities) == ("abc", entities)
    assert clip_text(None) == ("", None)


# well-formed HTML: теги парные, видимый текст = исходный
class _Balance(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack, self.text = [], ""

    def handle_starttag(self, tag, attrs):
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, f"перехлёст </{tag}>"

    def handle_data(self, data):
        self.text += data


def assert_well_formed(markup, expected_text):
    parser = _Balance()
    parser.feed(markup)
    parser.close()
    assert parser.stack == [] and parser.text == expected_text


def _random_entities(rng, length):
    """Непересекающиеся сущности с вложенностью (как их присылает Telegram)."""
    result, pos = [], 0
    while pos < length - 1 and len(result) < 4:
        start = rng.randint(pos, length - 1)
        size = rng.randint(1, min(8, length - start))
        kind = rng.choice(["bold", "italic", "text_link", "spoiler", "custom_emoji"])
        extra = {}
        if kind == "text_link":
            extra["url"] = "https://e.x/?a=1&b=2"
        if kind == "custom_emoji":
            extra["custom_emoji_id"] = "5"
        result.append(ent(kind, start, size, **extra))
        if size > 2 and kind != "custom_emoji" and rng.random() < 0.5:
            result.append(ent("underline", start + 1, size - 2))  # вложенная
        pos = start + size
    return result


def test_highlight_is_always_well_formed_on_random_input():
    rng = random.Random(7)
    alphabet = ["a", "b", " ", "\n", "<", "&", "🙂", "я"]
    for _ in range(400):
        old = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 25)))
        new = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 25)))
        units = len(new.encode("utf-16-le")) // 2
        ents = _random_entities(rng, units)
        # custom_emoji в тесте — произвольный диапазон: достаточно, что разметка парная
        out = highlight_changes(old, new, ents)
        assert_well_formed(out, new)


async def test_before_after_keeps_entities_in_both_halves():
    old = "привет мир"
    new = "привет, мир!"
    text = await before_after(
        "ru",
        old,
        new,
        [ent("text_link", 7, 3, url="https://x.y")],
        [ent("text_link", 8, 3, url="https://x.y")],
    )
    assert text.count('<a href="https://x.y">') == 2
    assert "<b>" in text.split("Стало")[1]
    assert not html_guard.problems("send_message", {"text": text, "parse_mode": "html"})


async def test_before_after_clips_text_and_entities_together():
    old = "a" * 3000
    new = "a" * 2990 + "Z" * 10
    text = await before_after(
        "ru", old, new, [ent("bold", 2500, 400)], [ent("bold", 2500, 400)]
    )
    visible = re.sub(r"<[^>]+>", "", text)
    assert len(html_lib.unescape(visible)) < 4096
    before = re.search(r"<blockquote expandable>(.*?)</blockquote>", text, re.S)
    assert "<b>" not in before.group(1)  # жирное лежало за краем обрезки
    assert not html_guard.problems("send_message", {"text": text, "parse_mode": "html"})


# ------------------------- (б) сквозные: классика и Rich -----------------------

EMOJI_ID = "5111222333444555666"


async def receive(bot, text, entities):
    msg = make_message(text, chat_id=CHAT, from_id=CHAT)
    msg.entities = [MessageEntity(**e) for e in entities]
    await on_business_message(msg, bot)
    return msg


async def edit(bot, msg, text, entities):
    edited = make_message(text, chat_id=CHAT, from_id=CHAT)
    edited.message_id = msg.message_id
    edited.entities = [MessageEntity(**e) for e in entities]
    await on_business_edited(edited, bot)


FMT_OLD = [
    ent("bold", 0, 6),
    ent("custom_emoji", 7, 2, custom_emoji_id=EMOJI_ID),
    ent("text_link", 10, 4, url="https://example.com/x"),
]
FMT_NEW = [
    ent("bold", 0, 6),
    ent("custom_emoji", 7, 2, custom_emoji_id=EMOJI_ID),
    ent("text_link", 10, 4, url="https://example.com/x"),
]


async def test_classic_text_edit_keeps_premium_emoji_format_and_links(ready, bot):
    msg = await receive(bot, "Привет 🙂 сайт", FMT_OLD)
    await edit(bot, msg, "Привет 🙂 сайт!!", FMT_NEW)

    (notice,) = bot.sent
    text = notice["text"]
    assert text.count(f'<tg-emoji emoji-id="{EMOJI_ID}">') == 2  # Было и Стало
    assert text.count('<a href="https://example.com/x">') == 2
    assert text.count("<b>Привет</b>") == 2
    assert "<b>!!</b>" in text.split("Стало")[1]
    assert not bot.html_problems


async def test_classic_caption_edit_keeps_entities(ready, bot):
    msg = make_message(caption="Подпись 🙂", chat_id=CHAT, from_id=CHAT)
    msg.photo = [types_file("p")]
    msg.caption_entities = [
        MessageEntity(**ent("custom_emoji", 8, 2, custom_emoji_id=EMOJI_ID))
    ]
    await on_business_message(msg, bot)

    edited = make_message(caption="Подпись 🙂 !", chat_id=CHAT, from_id=CHAT)
    edited.message_id = msg.message_id
    edited.photo = msg.photo
    edited.caption_entities = msg.caption_entities
    await on_business_edited(edited, bot)

    sent = [c["text"] for c in bot.sent]
    assert sent and sent[0].count(f'<tg-emoji emoji-id="{EMOJI_ID}">') == 2
    assert not bot.html_problems


def types_file(file_id):
    from .conftest import tg_file

    return tg_file(file_id)


def rich_dump(call):
    return call["rich_message"].model_dump_json()


async def test_rich_edit_history_keeps_entities_on_every_version(
    connection, api_bot, monkeypatch, bot
):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", True)
    await disable_module(CONNECTION_ID, "scam")
    msg = await receive(bot, "Привет 🙂 сайт", FMT_OLD)
    await edit(bot, msg, "Привет 🙂 сайт!", FMT_NEW)
    await edit(bot, msg, "Привет 🙂 сайт!!", FMT_NEW)

    dumps = [rich_dump(c) for c in bot.rich_sent] + [
        c["rich_message"].model_dump_json() for c in bot.edited if "rich_message" in c
    ]
    last = dumps[-1]
    # Было + Стало + одна ранняя версия в «истории»
    assert last.count(EMOJI_ID) >= 3
    assert last.count("https://example.com/x") >= 3


async def test_rich_multiline_text_keeps_formatting_per_line(
    connection, api_bot, monkeypatch, bot
):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", True)
    await disable_module(CONNECTION_ID, "scam")
    old = "первая\nвторая"
    bold_all = [ent("bold", 0, len(old))]
    msg = await receive(bot, old, bold_all)
    new = "первая\nвторая!"
    await edit(bot, msg, new, [ent("bold", 0, len(new))])
    dump = rich_dump(bot.rich_sent[0])
    assert dump.count('"type":"bold"') >= 4  # обе строки, и «Было», и «Стало»


def test_split_html_lines_reopens_tags_and_skips_blank_lines():
    assert split_html_lines("<b>a\nb</b>") == ["<b>a</b>", "<b>b</b>"]
    assert split_html_lines("<b>a\n\nb</b>") == [
        "<b>a</b>",
        "<b>b</b>",
    ]  # пустая строка
    assert split_html_lines('x <a href="u">l\nk</a>\ny') == [
        'x <a href="u">l</a>',
        '<a href="u">k</a>',
        "y",
    ]
    assert split_html_lines("\n \n") == []
    assert split_html_lines("\u2800") == ["\u2800"]  # «пустая» цитата не исчезает
