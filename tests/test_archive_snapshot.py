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


async def edit(bot, msg, text=None, **kwargs):
    edited = make_message(text, chat_id=CHAT, from_id=CHAT, **kwargs)
    edited.message_id = msg.message_id
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


async def test_rich_photo_caption_stays_below_by_default(rich, bot):
    msg = await receive(bot, caption="Мой чек", photo=photo("p"))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)

    assert bot.media_sent == [] and bot.sent == []  # одно сообщение, и это Rich
    (call,) = bot.rich_sent
    rich_message = call["rich_message"]
    html = rich_message.html
    assert "Сообщение удалено" in html and "tg-emoji" in html
    assert html.index("<img") < html.index("Мой чек")  # подпись под фото
    assert rich_message.media[0].media.media == "p"
    assert "Удалить у себя" in str(call["reply_markup"])


async def test_rich_photo_caption_above_if_it_was_above(rich, bot):
    msg = await receive(bot, caption="Мой чек", photo=photo("p"), above=True)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    html = bot.rich_sent[0]["rich_message"].html
    assert html.index("Мой чек") < html.index("<img")


async def test_rich_voice_has_text_before_the_file(rich, bot):
    msg = await receive(bot, caption="послушай", voice=tg_file("vo", duration=3))
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    html = bot.rich_sent[0]["rich_message"].html
    assert html.index("послушай") < html.index("<audio")
    assert bot.media_sent == []


async def test_rich_failure_falls_back_to_regular_notice(rich, bot, monkeypatch):
    msg = await receive(bot, caption="чек", photo=photo("p"))

    async def broken(**kw):
        raise RuntimeError("Bad Request: unsupported")

    monkeypatch.setattr(bot, "send_rich_message", broken)
    await on_business_deleted(deleted_event(CHAT, [msg.message_id]), bot)
    ((kind, kw),) = bot.media_sent
    assert kind == "photo" and "чек" in kw["caption"]


async def test_documents_and_stickers_do_not_use_rich(rich, bot):
    doc = await receive(bot, document=tg_file("d", file_name="a.png"))
    st = await receive(bot, sticker=tg_file("st"))
    await on_business_deleted(deleted_event(CHAT, [doc.message_id, st.message_id]), bot)
    assert bot.rich_sent == []
    assert [k for k, _ in bot.media_sent] == ["sticker"]
    assert len(bot.documents) == 1  # документ ушёл обычной отправкой


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
    html = call["rich_message"].html
    assert html.count("<tg-slideshow>") == 1 and html.count("<img") == 3
    assert "Поездка" in html and [
        m.media.media for m in call["rich_message"].media
    ] == ["p0", "p1", "p2"]
    assert bot.sent == [] and bot.media_sent == [] and bot.album_sent == []
    assert (
        len(await archive_events(client)) == 3
    )  # в вебе каждое сообщение — своя запись


async def test_deleted_album_regular_fallback_is_one_album_plus_button(ready, bot):
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

    (album,) = bot.album_sent
    assert [m.media for m in album["media"]] == ["p0", "p1", "p2"]
    assert "Поездка" in album["media"][0].caption and album["media"][1].caption is None
    assert len(bot.sent) == 1 and "Удалить у себя" in str(bot.sent[0]["reply_markup"])


async def test_forward_shown_once_for_forwarded_album(rich, bot):
    ids = []
    for index in range(2):
        msg = await receive(
            bot, photo=photo(f"p{index}"), group="g", forward=fwd_user()
        )
        ids.append(msg.message_id)
    await on_business_deleted(deleted_event(CHAT, ids), bot)
    html = bot.rich_sent[0]["rich_message"].html
    assert html.count("Переслано от") == 1 and "Вася" in html


async def test_separately_deleted_album_items_are_still_notified(rich, bot):
    first = await receive(bot, photo=photo("a"), group="g")
    await receive(bot, photo=photo("b"), group="g")
    await on_business_deleted(deleted_event(CHAT, [first.message_id]), bot)
    assert len(bot.rich_sent) == 1  # удалили одну фотку — одно уведомление


async def test_replaced_photo_rich_before_and_after(rich, bot):
    msg = await receive(bot, photo=photo("old", "u1"))
    await edit(bot, msg, photo=photo("new", "u2"))
    (call,) = bot.rich_sent
    html = call["rich_message"].html
    assert "Медиа заменено" in html and "Было" in html and "Стало" in html
    assert html.index("Было") < html.index("tg://photo?id=m0") < html.index("Стало")
    assert [m.media.media for m in call["rich_message"].media] == ["old", "new"]
    assert bot.sent == [] and bot.media_sent == []


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
