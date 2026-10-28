import pytest

from core import mentions

from .conftest import FakeBot


@pytest.fixture(autouse=True)
def clean_cache():
    mentions.clear_cache()
    yield
    mentions.clear_cache()


def test_format_mention_links_and_escaping():
    assert (
        mentions.format_mention("Аня", "anya_k", 5)
        == '<a href="https://t.me/anya_k">Аня</a>'
    )
    assert mentions.format_mention("Аня", None, 5) == '<a href="tg://user?id=5">Аня</a>'
    # имя пользователя может содержать HTML — оно обязано экранироваться
    evil = mentions.format_mention("<b>Хакер</b> & Ко", None, 5)
    assert "<b>" not in evil and "&lt;b&gt;" in evil and "&amp;" in evil
    # подозрительный username в ссылку не подставляем
    assert "t.me" not in mentions.format_mention("X", 'a"><script>', 5)
    assert (
        mentions.format_mention(None, None, 7, fallback="Игрок")
        == '<a href="tg://user?id=7">Игрок</a>'
    )


async def test_remember_avoids_api_calls():
    bot = FakeBot()
    bot.chat_names = {}
    mentions.remember(type("U", (), {"id": 9, "full_name": "Боря", "username": None})())
    assert await mentions.mention(bot, 9) == '<a href="tg://user?id=9">Боря</a>'
    assert bot.get_chat_calls == 0


async def test_resolve_uses_api_then_cache():
    bot = FakeBot()
    bot.chat_names = {9: ("Боря", "boris")}
    assert "Боря" in await mentions.mention(bot, 9)
    assert "Боря" in await mentions.mention(bot, 9)
    assert bot.get_chat_calls == 1


async def test_failure_falls_back_and_is_not_retried_immediately():
    bot = FakeBot()
    bot.chat_names = {}  # Telegram такого чата не знает
    first = await mentions.mention(bot, 77, fallback="Игрок")
    second = await mentions.mention(bot, 77, fallback="Игрок")
    assert first == second == '<a href="tg://user?id=77">Игрок</a>'
    assert bot.get_chat_calls == 1  # отрицательный результат тоже кешируется


def test_cache_is_bounded():
    for i in range(mentions._MAX_ENTRIES + 500):
        mentions.remember(
            type("U", (), {"id": i, "full_name": "n", "username": None})()
        )
    assert len(mentions._cache) <= mentions._MAX_ENTRIES
