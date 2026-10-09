import asyncio
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from tortoise import Tortoise

from api import setup_routers
from bot_instance import bot, dp
from config import TORTOISE_ORM, settings
from core.loader import load_modules
from core.logging_config import configure_logging
from core.mirror_manager import mirror_dispatcher, mirror_manager
from core.scheduler import run_emoji_clock

logger = logging.getLogger("bot.webhook")

_background_tasks: list[asyncio.Task] = []

_WEBHOOK_ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "callback_query",
    "my_chat_member",
    "business_connection",
    "business_message",
    "edited_business_message",
    "deleted_business_messages",
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()

    load_modules()
    await Tortoise.init(config=TORTOISE_ORM, _enable_global_fallback=True)

    if settings.WEBHOOK_URL:
        try:
            await bot.set_webhook(
                url=settings.WEBHOOK_URL,
                secret_token=settings.WEBHOOK_SECRET,
                drop_pending_updates=True,
                allowed_updates=_WEBHOOK_ALLOWED_UPDATES,
            )
        except Exception:
            # Временная ошибка Telegram API не должна ронять весь сервис
            # (включая мини-приложение и /health) на старте.
            logger.exception("Не удалось установить вебхук %s", settings.WEBHOOK_URL)
    else:
        logger.warning("WEBHOOK_BASE_URL не задан — вебхук не установлен")

    _background_tasks.append(asyncio.create_task(run_emoji_clock(bot)))

    await mirror_manager.start_all()

    yield

    for task in _background_tasks:
        task.cancel()
    for task in _background_tasks:
        try:
            await task
        except (Exception, asyncio.CancelledError):
            pass

    await mirror_manager.stop_all()
    await bot.session.close()
    await Tortoise.close_connections()


app = FastAPI(lifespan=lifespan)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(setup_routers(), prefix="/api")


@app.post(settings.WEBHOOK_PATH)
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=None),
):
    if not x_telegram_bot_api_secret_token or not hmac.compare_digest(
        x_telegram_bot_api_secret_token, settings.WEBHOOK_SECRET
    ):
        raise HTTPException(status_code=401, detail="Invalid secret token")

    data = await request.json()
    try:
        await dp.feed_webhook_update(bot, data)
    except Exception:
        # Раньше ошибка разбора апдейта (например, нетипизированное поле
        # в self-destruct-сообщении) проваливалась до UpdateLoggingMiddleware
        # и не оставляла следа в логах вообще — бот просто "молчал".
        logger.exception("Не удалось обработать апдейт: %s", data)
    return Response(status_code=200)


@app.post(f"{settings.MIRROR_WEBHOOK_PATH}/{{owner_id}}")
async def mirror_webhook(
    owner_id: int,
    request: Request,
    x_telegram_bot_api_secret_token: str = Header(default=None),
):
    if not mirror_manager.verify_secret(owner_id, x_telegram_bot_api_secret_token):
        raise HTTPException(status_code=401, detail="Invalid secret token")

    mirror_bot = mirror_manager.get_bot(owner_id)
    if not mirror_bot:
        raise HTTPException(status_code=404, detail="Mirror not running")

    data = await request.json()
    try:
        await mirror_dispatcher.feed_webhook_update(mirror_bot, data, owner_id=owner_id)
    except Exception:
        logger.exception(
            "Не удалось обработать апдейт зеркала owner_id=%s: %s", owner_id, data
        )
    return Response(status_code=200)


@app.get("/")
async def root():
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}
