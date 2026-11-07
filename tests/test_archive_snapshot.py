"""Архив: снимки сообщений, уведомление одним сообщением, пересылка, правки медиа."""

import types

import pytest

from config import settings
from core import database as db
from core.archive_notice import CAPTION_LIMIT, build_notice, visible_len
from core.snapshot import build_snapshot, edit_kind, entry_snapshot, public_view
from handlers.business_messages import on_business_message
from modules.archive import on_business_deleted, on_business_edited

from .conftest import CONNECTION_ID, deleted_event, make_message, tg_file

CHAT = 7


@pytest.fixture
async def ready(connection, api_bot, monkeypatch):
    """Обычный (не Rich) способ уведомления — он же запасной."""
    monkeypatch.setattr(settings, "ARCHIVE_RICH", False)
    await db.disable_module(CONNECTION_ID, "scam")
    return connection


@pytest.fixture
async def rich(connection, api_bot, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_RICH", True)
    await db.disable_module(CONNECTION_ID, "scam")
    return connection


async def receive(bot, text=None, forward=None, group=None, above=False, **kwargs):
    msg = make_message(text, chat_id=CHAT, from_id=CHAT, **kwargs)
    if forward is not None:
        msg.forward_origin = forward
    if group:
        msg.media_group_id = group
    if above:
        msg.show_caption_above_media = True
    await on_business_message(msg, bot)
    return msg


def fwd_user(user_id=5, name="Вася", username="vasya"):
    return types.SimpleNamespace(
        type="user",
        sender_user=types.SimpleNamespace(
            id=user_id, full_name=name, username=username
        ),
    )


# ------------------------------ снимок ----------------------------------------


def test_snapshot_kinds_and_fields():
    snap = build_snapshot(
        make_message(caption="подпись", photo=[tg_file("a"), tg_file("b")])
    )
    assert (
        snap["kind"] == "photo" and snap["file_id"] == "b" and snap["text"] == "подпись"
    )
    voice = build_snapshot(make_message(voice=tg_file("v", duration=11)))
    assert voice["kind"] == "voice" and voice["payload"]["duration"] == 11
    assert build_snapshot(make_message("привет"))["kind"] == "text"
    assert build_snapshot(make_message()) is None


def test_snapshot_payload_kinds():
    msg = make_message()
    msg.location = types.SimpleNamespace(latitude=1.5, longitude=2.5)
    snap = build_snapshot(msg)
    assert snap["kind"] == "location" and snap["payload"] == {
        "latitude": 1.5,
        "longitude": 2.5,
    }


def test_snapshot_forward_origin():
    msg = make_message("привет")
    msg.forward_origin = fwd_user()
    assert build_snapshot(msg)["forward"] == {
        "type": "user",
        "id": 5,
        "name": "Вася",
        "username": "vasya",
    }


def test_edit_kind_detection():
    base = {"kind": "photo", "text": "a", "file_unique_id": "u1"}
    assert edit_kind(base, {**base, "text": "b"}) == "caption"
    assert edit_kind(base, {**base, "text": ""}) == "caption_removed"
    assert edit_kind(base, {**base, "file_unique_id": "u2"}) == "media"
    assert (
        edit_kind(base, {**base, "file_unique_id": "u2", "text": "b"})
        == "media_caption"
    )
    assert edit_kind(base, dict(base)) is None
    assert (
        edit_kind({"kind": "text", "text": "a"}, {"kind": "text", "text": "b"})
        == "text"
    )
    # у старых записей нет file_unique_id — замену медиа определить нельзя, но и ложных срабатываний нет
    assert (
        edit_kind({**base, "file_unique_id": None}, {**base, "file_unique_id": "u2"})
        is None
    )


def test_public_view_hides_file_id_and_raw():
    view = public_view(
        {"kind": "photo", "file_id": "secret", "raw_json": {"x": 1}, "file_size": 5}
    )
    assert "file_id" not in view and "raw_json" not in view and view["has_file"] is True


def test_notice_fits_telegram_caption_limit():
    snap = {"kind": "photo", "text": "я" * 5000, "entities": None}
    notice = build_notice("ru", "Аня", snap, limit=CAPTION_LIMIT)
    assert visible_len(notice) <= CAPTION_LIMIT and notice.count("…") == 1


# --------------------- удаление: одно сообщение ------------------------------


async def test_deleted_voice_is_one_message_with_caption_and_button(ready, bot):
    msg = await receive(bot, voice=tg_file("vo", duration=11))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    assert bot.sent == []  # отдельного текстового уведомления больше нет
    ((kind, kw),) = bot.media_sent
    assert kind == "voice" and kw["voice"] == "vo"
    assert "Сообщение удалено" in kw["caption"] and "Собеседник" in kw["caption"]
    assert "Удалить у себя" in str(kw["reply_markup"])
    assert "[медиа-сообщение]" not in kw["caption"]


async def test_deleted_photo_caption_goes_above_media(ready, bot):
    msg = await receive(bot, caption="Мой чек", photo=[tg_file("p")])
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    ((kind, kw),) = bot.media_sent
    assert kind == "photo" and kw["show_caption_above_media"] is True
    assert "Мой чек" in kw["caption"]


async def test_deleted_sticker_is_one_message_with_buttons(ready, bot):
    msg = await receive(bot, sticker=tg_file("st", is_animated=False, is_video=False))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    assert bot.sent == []  # никаких отдельных уведомлений и ответов на них
    ((kind, kw),) = bot.media_sent
    assert kind == "sticker" and kw["sticker"] == "st" and "reply_parameters" not in kw
    rows = kw["reply_markup"].inline_keyboard
    assert rows[0][0].callback_data == "archive:info"  # «Сообщение удалено!»
    assert rows[1][0].url == "tg://user?id=7"  # профиль собеседника
    assert rows[-1][0].callback_data == "archive:delete_notice"


async def test_forwarded_sticker_gets_forward_button(ready, bot):
    msg = await receive(bot, sticker=tg_file("st"), forward=fwd_user())
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    rows = bot.media_sent[0][1]["reply_markup"].inline_keyboard
    button = next(r[0] for r in rows if "Вася" in r[0].text)
    assert button.url == "https://t.me/vasya"
    assert button.icon_custom_emoji_id == "5260450573768990626"


async def test_profile_button_is_dropped_if_telegram_rejects_it(
    ready, bot, monkeypatch
):
    msg = await receive(bot, sticker=tg_file("st"))
    calls = []
    original = bot.send_sticker

    async def picky(**kw):
        calls.append(kw)
        if any(b.url for row in kw["reply_markup"].inline_keyboard for b in row):
            raise RuntimeError("BUTTON_USER_PRIVACY_RESTRICTED")
        return await original(**kw)

    monkeypatch.setattr(bot, "send_sticker", picky)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    assert len(calls) == 2 and len(bot.media_sent) == 1


async def test_deleted_location_is_one_message_without_duplicated_text(ready, bot):
    msg = make_message(chat_id=CHAT, from_id=CHAT)
    msg.location = types.SimpleNamespace(latitude=10.0, longitude=20.0)
    await on_business_message(msg, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    assert bot.sent == []  # координаты не дублируются текстом
    ((kind, kw),) = bot.media_sent
    assert kind == "location" and kw["latitude"] == 10.0
    assert kw["reply_markup"].inline_keyboard[0][0].callback_data == "archive:info"


async def test_info_button_answers_with_toast(ready, bot):
    from modules.archive import on_info

    class Call:
        from_user = types.SimpleNamespace(id=42)

        def __init__(self):
            self.answers = []

        async def answer(self, text=None, **kw):
            self.answers.append(text)

    call = Call()
    await on_info(call)
    assert "удалил" in call.answers[0]


async def test_deleted_text_unchanged(ready, bot):
    msg = await receive(bot, "секрет")
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    (notice,) = bot.sent
    assert "секрет" in notice["text"] and "Удалить у себя" in str(
        notice["reply_markup"]
    )
    assert bot.media_sent == []


async def test_missing_file_is_reported_not_silent(ready, bot, monkeypatch):
    msg = await receive(bot, voice=tg_file("vo"))

    async def boom(**kw):
        raise RuntimeError("file_id expired")

    monkeypatch.setattr(bot, "send_voice", boom)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    assert "не удалось восстановить" in bot.sent[0]["text"]


# ------------------------------ пересылка -------------------------------------


async def test_forwarded_text_shows_origin_with_link(ready, bot):
    msg = await receive(bot, "переслал", forward=fwd_user())
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    text = bot.sent[0]["text"]
    assert (
        "Переслано от" in text
        and 'href="https://t.me/vasya"' in text
        and "Вася" in text
    )


async def test_forwarded_voice_caption_mentions_origin(ready, bot):
    msg = await receive(bot, voice=tg_file("vo"), forward=fwd_user(username=None))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    caption = bot.media_sent[0][1]["caption"]
    assert "Переслано от" in caption and "tg://user?id=5" in caption


async def test_forwarded_from_hidden_user_is_plain_name(ready, bot):
    hidden = types.SimpleNamespace(type="hidden_user", sender_user_name="Скрытый")
    msg = await receive(bot, "текст", forward=hidden)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    assert "Скрытый" in bot.sent[0]["text"] and "Переслано от" in bot.sent[0]["text"]


# ------------------------------- правки ---------------------------------------


async def edit(bot, msg, text=None, group=None, **kwargs):
    edited = make_message(text, chat_id=CHAT, from_id=CHAT, **kwargs)
    edited.message_id = msg.message_id
    if group:
        edited.media_group_id = group
    await on_business_edited(edited, bot)


async def archive_events(client):
    return (await client.get("/api/archive", headers=client.owner)).json()["entries"]


async def test_replaced_photo_sends_notice_then_before_and_after(ready, bot, client):
    msg = await receive(
        bot,
        photo=[types.SimpleNamespace(file_id="old", file_unique_id="u1", file_size=10)],
    )
    await edit(
        bot,
        msg,
        photo=[types.SimpleNamespace(file_id="new", file_unique_id="u2", file_size=10)],
    )

    (notice,) = bot.sent
    assert "Медиа заменено" in notice["text"]
    sent = [(k, kw[k], kw["caption"]) for k, kw in bot.media_sent]
    assert [s[:2] for s in sent] == [("photo", "old"), ("photo", "new")]
    assert "Было" in sent[0][2] and "Стало" in sent[1][2]

    (entry,) = await archive_events(client)
    assert entry["event"] == "edited" and entry["edit_kind"] == "media"
    assert entry["old"]["has_file"] and entry["new"]["has_file"]
    old_file = await client.get(
        f"/api/archive/{entry['log_id']}/media?which=old", headers=client.owner
    )
    new_file = await client.get(
        f"/api/archive/{entry['log_id']}/media?which=new", headers=client.owner
    )
    assert (
        old_file.content == b"bytes:files/old"
        and new_file.content == b"bytes:files/new"
    )


async def test_caption_edit_and_removal_are_reported(ready, bot, client):
    """В «Было/Стало» часы — премиум-эмодзи, пустая подпись — невидимый символ."""
    uid = types.SimpleNamespace(file_id="p", file_unique_id="u1", file_size=10)
    msg = await receive(bot, caption="до", photo=[uid])
    await edit(bot, msg, caption="после", photo=[uid])
    await edit(bot, msg, photo=[uid])  # подпись удалили
    kinds = sorted(e["edit_kind"] for e in await archive_events(client))
    assert kinds == ["caption", "caption_removed"]
    assert "Подпись изменена" in bot.sent[0]["text"]
    assert "\u2800" in bot.sent[1]["text"]  # «стало» пусто: невидимый символ


async def test_unchanged_edit_is_silent(ready, bot):
    uid = types.SimpleNamespace(file_id="p", file_unique_id="u1", file_size=10)
    msg = await receive(bot, caption="то же", photo=[uid])
    await edit(bot, msg, caption="то же", photo=[uid])
    assert bot.sent == [] and bot.media_sent == []


async def test_text_edit_still_works(ready, bot):
    msg = await receive(bot, "было")
    await edit(bot, msg, "стало")
    assert "Сообщение изменено" in bot.sent[0]["text"]


# --------------------------- файлы и хранение ---------------------------------


async def test_regular_media_is_not_stored_as_bytes(ready, bot):
    msg = await receive(bot, photo=[tg_file("p")])
    entry = await db.get_history_entry(CONNECTION_ID, CHAT, msg.message_id)
    assert entry["media_data"] is None and entry["file_id"] == "p"
    assert (
        entry["media_status"] == "remote" and entry_snapshot(entry)["kind"] == "photo"
    )


async def test_legacy_rows_without_snapshot_still_work(ready, bot):
    await db.save_history(CONNECTION_ID, CHAT, 999, False, "старое", 1)
    entry = await db.get_history_entry(CONNECTION_ID, CHAT, 999)
    assert entry_snapshot(entry)["kind"] == "text"


# ------------------------------ Rich Message ----------------------------------


def photo(file_id, uid=None):
    return [
        types.SimpleNamespace(
            file_id=file_id, file_unique_id=uid or file_id, file_size=10
        )
    ]


def plain(value):
    """RichText -> простая строка."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(plain(v) for v in value)
    if hasattr(value, "alternative_text"):
        return value.alternative_text
    return plain(getattr(value, "text", ""))


def block_text(block):
    kind = block.type
    if kind in ("paragraph", "footer", "heading"):
        return plain(block.text)
    if kind in ("blockquote", "details"):
        inner = " ".join(block_text(b) for b in block.blocks)
        return (plain(block.summary) + " " if kind == "details" else "") + inner
    return ""


def kinds(rich_message):
    return [b.type for b in rich_message.blocks]


def texts(rich_message):
    return " | ".join(filter(None, (block_text(b) for b in rich_message.blocks)))


def media_of(block):
    for field in ("photo", "video", "animation", "audio", "voice_note", "document"):
        if hasattr(block, field):
            return getattr(block, field).media
    return None


async def test_rich_photo_caption_stays_below_by_default(rich, bot):
    msg = await receive(bot, caption="Мой чек", photo=photo("p"))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    assert bot.media_sent == [] and bot.sent == []  # одно сообщение, и это Rich
    (call,) = bot.rich_sent
    message = call["rich_message"]
    types_ = kinds(message)
    assert types_.index("photo") < types_.index("blockquote")  # подпись под фото
    assert "Сообщение удалено" in texts(message) and "Мой чек" in texts(message)
    assert media_of(message.blocks[types_.index("photo")]) == "p"
    assert "Удалить у себя" in str(call["reply_markup"])


async def test_rich_header_uses_archive_box_not_trash(rich, bot):
    msg = await receive(bot, photo=photo("p"))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    first = bot.rich_sent[0]["rich_message"].blocks[0].text
    assert first[0].custom_emoji_id == "5258389041006518073"


async def test_rich_photo_caption_above_if_it_was_above(rich, bot):
    msg = await receive(bot, caption="Мой чек", photo=photo("p"), above=True)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    types_ = kinds(bot.rich_sent[0]["rich_message"])
    assert types_.index("blockquote") < types_.index("photo")


async def test_voice_is_regular_by_default_but_can_go_rich(rich, bot, monkeypatch):
    msg = await receive(bot, caption="послушай", voice=tg_file("vo", duration=3))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    # на iPhone Rich показывает голосовое как «Unknown track» — по умолчанию обычное
    assert bot.rich_sent == [] and bot.media_sent[0][0] == "voice"

    monkeypatch.setattr(settings, "ARCHIVE_RICH_KINDS", "photo,voice")
    msg2 = await receive(bot, caption="ещё", voice=tg_file("vo2", duration=3))
    await on_business_deleted(deleted_event(CHAT, [msg2.message_id]), bot)
    message = bot.rich_sent[0]["rich_message"]
    assert "voice_note" in kinds(message)
    assert kinds(message).index("blockquote") < kinds(message).index("voice_note")


async def test_rich_failure_falls_back_to_regular_notice(rich, bot, monkeypatch):
    msg = await receive(bot, caption="чек", photo=photo("p"))

    async def broken(**kw):
        raise RuntimeError("Bad Request: unsupported")

    monkeypatch.setattr(bot, "send_rich_message", broken)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    ((kind, kw),) = bot.media_sent
    assert kind == "photo" and "чек" in kw["caption"]


async def test_document_goes_rich_but_sticker_does_not(rich, bot):
    doc = await receive(bot, caption="скан", document=tg_file("d", file_name="a.png"))
    st = await receive(bot, sticker=tg_file("st"))
    await on_business_deleted(deleted_event(CHAT, [doc.message_id, st.message_id]), bot)
    (call,) = bot.rich_sent  # документ — одним Rich-сообщением с блоком document
    assert "document" in kinds(call["rich_message"])
    assert [k for k, _ in bot.media_sent] == ["sticker"]
    assert bot.documents == []


async def test_deleted_album_is_one_rich_carousel(rich, bot, client):
    ids = []
    for index in range(3):
        msg = await receive(
            bot,
            caption="Поездка" if index == 0 else None,
            photo=photo(f"p{index}"),
            group="album-1",
        )
        ids.append(msg.message_id)
    await on_business_deleted(deleted_event(CHAT, ids), bot)

    (call,) = bot.rich_sent
    message = call["rich_message"]
    slideshow = next(b for b in message.blocks if b.type == "slideshow")
    assert [media_of(b) for b in slideshow.blocks] == ["p0", "p1", "p2"]
    assert "Поездка" in texts(message)
    assert bot.sent == [] and bot.media_sent == [] and bot.album_sent == []
    assert len(await archive_events(client)) == 3


async def test_album_style_collage_is_configurable(rich, bot, monkeypatch):
    monkeypatch.setattr(settings, "ARCHIVE_ALBUM_STYLE", "collage")
    ids = [
        (await receive(bot, photo=photo(f"p{i}"), group="g")).message_id
        for i in range(2)
    ]
    await on_business_deleted(deleted_event(CHAT, ids), bot)
    assert "collage" in kinds(bot.rich_sent[0]["rich_message"])


async def test_document_album_is_one_rich_message(rich, bot):
    ids = [
        (
            await receive(
                bot, document=tg_file(f"d{i}", file_name=f"{i}.png"), group="g"
            )
        ).message_id
        for i in range(3)
    ]
    await on_business_deleted(deleted_event(CHAT, ids), bot)
    (call,) = bot.rich_sent
    assert kinds(call["rich_message"]).count("document") == 3
    assert bot.sent == []  # никакого «сырого» второго сообщения


async def test_regular_album_fallback_starts_with_header_then_files(ready, bot):
    ids = []
    for index in range(3):
        msg = await receive(
            bot,
            caption="Поездка" if index == 0 else None,
            photo=photo(f"p{index}"),
            group="g",
        )
        ids.append(msg.message_id)
    await on_business_deleted(deleted_event(CHAT, ids), bot)

    (header,) = bot.sent
    assert "Сообщение удалено" in header["text"] and "Поездка" in header["text"]
    assert "Удалить у себя" in str(header["reply_markup"])
    (album,) = bot.album_sent
    assert [m.media for m in album["media"]] == ["p0", "p1", "p2"]
    assert all(m.caption is None for m in album["media"])


async def test_forward_shown_once_for_forwarded_album(rich, bot):
    ids = [
        (
            await receive(bot, photo=photo(f"p{i}"), group="g", forward=fwd_user())
        ).message_id
        for i in range(2)
    ]
    await on_business_deleted(deleted_event(CHAT, ids), bot)
    text = texts(bot.rich_sent[0]["rich_message"])
    assert text.count("Переслано от") == 1 and "Вася" in text


async def test_forwarded_photo_with_caption_in_rich(rich, bot):
    msg = await receive(
        bot, caption="пересланное", photo=photo("p"), forward=fwd_user()
    )
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    text = texts(bot.rich_sent[0]["rich_message"])
    assert "Переслано от" in text and "Вася" in text and "пересланное" in text


async def test_separately_deleted_album_items_are_still_notified(rich, bot):
    first = await receive(bot, photo=photo("a"), group="g")
    await receive(bot, photo=photo("b"), group="g")
    await on_business_deleted(deleted_event(CHAT, [first.message_id]), bot)
    assert len(bot.rich_sent) == 1


async def test_replaced_photo_rich_before_and_after_with_colons(rich, bot):
    msg = await receive(bot, photo=photo("old", "u1"))
    await edit(bot, msg, photo=photo("new", "u2"))
    (call,) = bot.rich_sent
    message = call["rich_message"]
    text = texts(message)
    assert "Медиа заменено" in text and "Было:" in text and "Стало:" in text
    assert [media_of(b) for b in message.blocks if b.type == "photo"] == ["old", "new"]
    assert bot.sent == [] and bot.media_sent == []


async def test_replaced_document_is_rich_too(rich, bot):
    msg = await receive(bot, document=tg_file("d1", file_unique_id="u1", file_name="a"))
    await edit(bot, msg, document=tg_file("d2", file_unique_id="u2", file_name="b"))
    (call,) = bot.rich_sent
    assert kinds(call["rich_message"]).count("document") == 2


async def test_replaced_voice_uses_regular_before_and_after(rich, bot):
    msg = await receive(bot, voice=tg_file("v1", file_unique_id="u1"))
    await edit(bot, msg, voice=tg_file("v2", file_unique_id="u2"))
    assert bot.rich_sent == [] and len(bot.media_sent) == 2


async def test_rescued_bytes_are_not_sent_through_rich(rich, bot):
    msg = await receive(bot, photo=photo("p"))
    entry = await db.get_history_entry(CONNECTION_ID, CHAT, msg.message_id)
    from core.archive_rich import can_use_rich

    assert can_use_rich([(entry_snapshot(entry), entry)]) is True
    assert (
        can_use_rich([(entry_snapshot(entry), {**entry, "media_data": b"x"})]) is False
    )


# ----------------------- история правок в одном сообщении ----------------------


async def test_all_edits_of_one_message_share_one_notice(rich, bot, client):
    msg = await receive(bot, "v1")
    await edit(bot, msg, "v2")
    await edit(bot, msg, "v3")
    await edit(bot, msg, "v4")

    assert len(bot.rich_sent) == 1  # одно уведомление…
    assert len(bot.edited) == 2  # …которое обновили на 2-й и 3-й правках
    last = bot.edited[-1]["rich_message"]
    text = texts(last)
    assert "Было: | v3" in text.replace("\n", " ") or "v3" in text
    assert "v4" in text and "Ранние версии: 2" in text and "Изменений: 3" in text
    assert "details" in kinds(last)
    # версии идут по порядку: в свёрнутом блоке самая ранняя
    details = next(b for b in last.blocks if b.type == "details")
    assert "v1" in block_text(details) and "v2" in block_text(details)
    assert block_text(details).index("v1") < block_text(details).index("v2")
    assert bot.edited[-1]["message_id"] == 1001


async def test_first_edit_has_no_collapsed_history(rich, bot):
    msg = await receive(bot, "было")
    await edit(bot, msg, "стало")
    message = bot.rich_sent[0]["rich_message"]
    assert "details" not in kinds(message) and "Изменений: 1" in texts(message)
    assert "Сообщение изменено" in texts(message)


async def test_edit_goes_to_new_message_if_notice_is_gone(rich, bot, monkeypatch):
    msg = await receive(bot, "a")
    await edit(bot, msg, "b")

    async def gone(**kw):
        raise RuntimeError("Bad Request: message to edit not found")

    monkeypatch.setattr(bot, "edit_message_text", gone)
    await edit(bot, msg, "c")
    assert len(bot.rich_sent) == 2  # новое уведомление, а не тишина
    assert "Изменений: 2" in texts(
        bot.rich_sent[1]["rich_message"]
    )  # история сохранена


async def test_different_messages_do_not_share_a_notice(rich, bot):
    first = await receive(bot, "a")
    second = await receive(bot, "x")
    await edit(bot, first, "b")
    await edit(bot, second, "y")
    assert len(bot.rich_sent) == 2 and bot.edited == []


async def test_caption_edit_shows_the_photo_between_header_and_diff(rich, bot):
    uid = photo("p", "u1")
    msg = await receive(bot, caption="до", photo=uid)
    await edit(bot, msg, caption="после", photo=uid)
    message = bot.rich_sent[0]["rich_message"]
    types_ = kinds(message)
    assert "Подпись изменена" in texts(message)
    assert types_.index("photo") < types_.index("blockquote")  # файл над «Было/Стало»


async def test_caption_edit_of_album_shows_whole_album(rich, bot):
    first = await receive(bot, caption="до", photo=photo("a", "ua"), group="g")
    await receive(bot, photo=photo("b", "ub"), group="g")
    await edit(bot, first, caption="после", photo=photo("a", "ua"), group="g")
    message = bot.rich_sent[0]["rich_message"]
    slideshow = next(b for b in message.blocks if b.type == "slideshow")
    assert [media_of(b) for b in slideshow.blocks] == ["a", "b"]


async def test_caption_edit_without_rich_photo_kind_is_text_only(
    rich, bot, monkeypatch
):
    monkeypatch.setattr(settings, "ARCHIVE_RICH_KINDS", "document")
    uid = photo("p", "u1")
    msg = await receive(bot, caption="до", photo=uid)
    await edit(bot, msg, caption="после", photo=uid)
    assert "photo" not in kinds(bot.rich_sent[0]["rich_message"])


async def test_edit_history_is_stored_with_notice_id(rich, bot):
    msg = await receive(bot, "a")
    await edit(bot, msg, "b")
    rows = await db.get_edit_history(CONNECTION_ID, CHAT, msg.message_id)
    assert rows[0]["notice_message_id"] == 1001 and rows[0]["edit_kind"] == "text"


# ------------------------------ кнопки и подарки ------------------------------


async def test_button_roles_and_colors(ready, bot):
    msg = await receive(bot, sticker=tg_file("st"), forward=fwd_user())
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    rows = bot.media_sent[0][1]["reply_markup"].inline_keyboard
    stub, profile, forward, delete = (r[0] for r in rows)
    assert stub.callback_data == "archive:info" and stub.style is None
    assert stub.icon_custom_emoji_id == "5258389041006518073"  # коробка, не мусорка
    assert profile.text.startswith("Собеседник:") and profile.style == "primary"
    assert forward.style == "primary"
    assert (
        delete.style == "danger"
        and delete.icon_custom_emoji_id == "5258130763148172425"
    )


async def test_gift_is_resent_as_its_sticker_with_summary_button(ready, bot):
    from aiogram.types import Gift, GiftInfo, Sticker

    sticker = Sticker(
        file_id="gift-st",
        file_unique_id="u",
        type="regular",
        width=512,
        height=512,
        is_animated=True,
        is_video=False,
    )
    msg = make_message(chat_id=CHAT, from_id=CHAT)
    msg.gift = GiftInfo(
        gift=Gift(id="g1", sticker=sticker, star_count=25), text="с днём"
    )
    await on_business_message(msg, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    assert bot.sent == []
    ((kind, kw),) = bot.media_sent
    assert kind == "sticker" and kw["sticker"] == "gift-st"
    summary = kw["reply_markup"].inline_keyboard[1][0]
    assert (
        "25" in summary.text and summary.icon_custom_emoji_id == "5963213811597970978"
    )


async def test_gift_without_sticker_gets_formatted_text(ready, bot):
    msg = make_message(chat_id=CHAT, from_id=CHAT)
    msg.gift = types.SimpleNamespace(text="привет")
    await on_business_message(msg, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    text = bot.sent[0]["text"]
    assert "5963213811597970978" in text and "<blockquote>" in text and "<b>" in text


def test_dice_results_are_described():
    from core.archive_notice import describe_dice

    assert "5" in describe_dice("ru", "🎲", 5) and "⚄" in describe_dice("ru", "🎲", 5)
    assert "Гол" in describe_dice("ru", "⚽", 4) and "Мимо" in describe_dice(
        "ru", "⚽", 1
    )
    assert "Страйк" in describe_dice("ru", "🎳", 6)
    assert "Яблочко" in describe_dice("ru", "🎯", 6)
    assert "7️⃣ 7️⃣ 7️⃣" in describe_dice("ru", "🎰", 64) and "Джекпот" in describe_dice(
        "ru", "🎰", 64
    )
    assert "BAR BAR BAR" in describe_dice("ru", "🎰", 1)


async def test_dice_notice_is_bold_quote(ready, bot):
    msg = make_message(chat_id=CHAT, from_id=CHAT)
    msg.dice = types.SimpleNamespace(emoji="🎰", value=64)
    await on_business_message(msg, bot)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    text = bot.sent[0]["text"]
    assert "<blockquote><b>🎰" in text and "Джекпот" in text


def test_html_to_rich_converts_our_markup():
    from core.rich_text import html_to_rich

    result = html_to_rich(
        '<tg-emoji emoji-id="1">📦</tg-emoji> <b>Привет</b> <a href="tg://user?id=7">Аня &amp; Ко</a>'
    )
    assert [getattr(r, "type", r) for r in result] == [
        "custom_emoji",
        " ",
        "bold",
        " ",
        "url",
    ]
    assert result[4].text == "Аня & Ко" and result[4].url == "tg://user?id=7"
    assert html_to_rich("просто") == "просто" and html_to_rich("") == ""
