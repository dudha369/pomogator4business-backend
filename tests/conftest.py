"""Общие фикстуры: база SQLite в памяти и фейковый бот.

Переменные окружения выставляются ДО импорта config/приложения — иначе
настройки возьмутся из реального окружения."""

import os
import types
from datetime import datetime, timezone

os.environ["BOT_TOKEN"] = "123456:TEST"
# по умолчанию SQLite в памяти; TEST_DB_URL позволяет прогнать тесты на Postgres
os.environ["DB_URL"] = os.environ.get("TEST_DB_URL", "sqlite://:memory:")
os.environ.setdefault("WEBHOOK_SECRET", "test-secret")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from tortoise import Tortoise  # noqa: E402

import bot_instance  # noqa: E402
from config import TORTOISE_ORM  # noqa: E402
from core import database as db  # noqa: E402
from core.loader import load_modules  # noqa: E402

bot_instance.setup_routes()
load_modules()

OWNER_ID = 42
CONNECTION_ID = "conn-1"
NOW = 1_800_000_000


@pytest_asyncio.fixture
async def database():
    on_postgres = not os.environ["DB_URL"].startswith("sqlite")
    await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)
    if on_postgres:
        # чистая схема для каждого теста (БД для тестов должна существовать заранее)
        await Tortoise.get_connection("default").execute_script(
            "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
        )
    await Tortoise.generate_schemas()
    yield
    await Tortoise.close_connections()


@pytest_asyncio.fixture
async def connection(database):
    await db.upsert_connection(CONNECTION_ID, OWNER_ID, OWNER_ID, True)
    return await db.get_connection(CONNECTION_ID)


class FakeBot:
    """Записывает вызовы Bot API, которыми пользуется код бота."""

    def __init__(self):
        self.sent = []  # send_message
        self.edited = []  # edit_message_text
        self.deleted = []  # delete_business_messages
        self.reads = []  # read_business_message
        self.documents = []  # send_document
        self.media_sent = (
            []
        )  # send_photo/video/... (повторная отправка удалённого медиа)
        self._next_id = 1000

    async def send_message(self, **kwargs):
        self.sent.append(kwargs)
        self._next_id += 1
        return types.SimpleNamespace(message_id=self._next_id)

    async def edit_message_text(self, **kwargs):
        self.edited.append(kwargs)

    async def delete_business_messages(self, **kwargs):
        self.deleted.append(kwargs)

    async def read_business_message(self, **kwargs):
        self.reads.append(kwargs)

    async def send_document(self, **kwargs):
        self.documents.append(kwargs)

    # --- скачивание файлов и повторная отправка медиа ---
    async def get_file(self, file_id):
        return types.SimpleNamespace(file_path=f"files/{file_id}")

    async def download_file(self, file_path):
        import io

        return io.BytesIO(b"bytes:" + file_path.encode())

    async def _send_media(self, kind, **kwargs):
        self.media_sent.append((kind, kwargs))
        return types.SimpleNamespace(message_id=1)

    async def send_photo(self, **kw):
        return await self._send_media("photo", **kw)

    async def send_video(self, **kw):
        return await self._send_media("video", **kw)

    async def send_voice(self, **kw):
        return await self._send_media("voice", **kw)

    async def send_video_note(self, **kw):
        return await self._send_media("video_note", **kw)

    async def send_animation(self, **kw):
        return await self._send_media("animation", **kw)

    async def send_audio(self, **kw):
        return await self._send_media("audio", **kw)

    async def send_sticker(self, **kw):
        return await self._send_media("sticker", **kw)

    async def get_me(self):
        return types.SimpleNamespace(id=1, username="testbot")

    # имена для get_chat: {id: (full_name, username)}; нет в словаре — Telegram «не знает» чат
    chat_names = None
    get_chat_calls = 0

    async def get_chat(self, chat_id):
        self.get_chat_calls += 1
        if self.chat_names is not None:
            if chat_id not in self.chat_names:
                raise RuntimeError("chat not found")
            name, username = self.chat_names[chat_id]
            return types.SimpleNamespace(full_name=name, username=username)
        return types.SimpleNamespace(full_name=f"Chat {chat_id}", username=None)


@pytest.fixture
def bot():
    return FakeBot()


_counter = {"n": 0}


def make_message(
    text=None,
    chat_id=7,
    from_id=7,
    *,
    caption=None,
    ts=NOW,
    connection_id=CONNECTION_ID,
    is_bot=False,
    chat_type="private",
    reply_to=None,
    first_name="Аня",
    photo=None,
    video=None,
    voice=None,
    video_note=None,
    animation=None,
    audio=None,
    document=None,
    sticker=None,
):
    """Минимальное похожее на aiogram Message сообщение (без медиа)."""
    _counter["n"] += 1
    return types.SimpleNamespace(
        message_id=_counter["n"],
        business_connection_id=connection_id,
        text=text,
        caption=caption,
        chat=types.SimpleNamespace(id=chat_id, type=chat_type, first_name=first_name),
        from_user=types.SimpleNamespace(
            id=from_id,
            first_name=first_name,
            last_name=None,
            full_name=first_name,
            username=None,
            language_code="ru",
            is_premium=None,
            is_bot=is_bot,
        ),
        date=datetime.fromtimestamp(ts, timezone.utc),
        photo=photo,
        video=video,
        voice=voice,
        video_note=video_note,
        animation=animation,
        audio=audio,
        document=document,
        sticker=sticker,
        reply_to_message=reply_to,
    )


# ------------------------------- API ----------------------------------------

import hashlib  # noqa: E402
import hmac  # noqa: E402
import json  # noqa: E402
import time  # noqa: E402
import urllib.parse  # noqa: E402

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from api import setup_routers  # noqa: E402
from config import settings  # noqa: E402


def init_data_headers(user_id=OWNER_ID):
    """Заголовок авторизации мини-приложения с валидной подписью initData."""
    data = {
        "auth_date": str(int(time.time())),
        "user": json.dumps({"id": user_id, "first_name": "Owner"}),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(
        b"WebAppData", settings.BOT_TOKEN.encode(), hashlib.sha256
    ).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return {"X-Telegram-Init-Data": urllib.parse.urlencode(data)}


@pytest_asyncio.fixture
async def client(connection):
    app = FastAPI()
    app.include_router(setup_routers(), prefix="/api")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        c.owner = init_data_headers()
        yield c


@pytest.fixture
def api_bot(monkeypatch, bot):
    """Подменяет глобальный bot из bot_instance (его используют API-хендлеры)."""
    import bot_instance

    for name in (
        "send_message",
        "read_business_message",
        "send_document",
        "get_chat",
        "get_me",
    ):
        monkeypatch.setattr(bot_instance.bot, name, getattr(bot, name))
    return bot


def tg_file(file_id="f1", size=1000, **extra):
    """Объект «файл Telegram» (photo/video/voice/...): id и размер."""
    return types.SimpleNamespace(file_id=file_id, file_size=size, **extra)


def deleted_event(chat_id, message_ids, connection_id=CONNECTION_ID):
    return types.SimpleNamespace(
        business_connection_id=connection_id,
        chat=types.SimpleNamespace(id=chat_id, full_name="Аня", username=None),
        message_ids=message_ids,
    )
