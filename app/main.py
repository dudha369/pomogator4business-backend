import asyncio
import contextlib
import hmac
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from tortoise import Tortoise

from app.features.emoji_clock.bot import run_emoji_clock
from app.features.mirror.manager import mirror_dispatcher, mirror_manager
from app.features.ops import sink as ops_sink
from app.features.ops import startup as ops_startup
from app.features.ops.health_api import health_router
from app.features.ops.middleware import OpsContextMiddleware, RequestContextMiddleware
from app.features.reminders.bot import run_reminders_loop
from app.features.scheduled.service import run_scheduled_loop
from app.features.userbot.manager import manager as userbot_manager
from app.features.vault import service as vault
from app.platform.api import setup_routers
from app.platform.api.errors import ApiErrorCode, cors_headers, install_error_handlers
from app.platform.loader import load_commands
from app.platform.logging_config import configure_logging
from app.platform.retention import run_retention_loop
from app.platform.tasks import spawn
from bot_instance import bot, dp
from config import TORTOISE_ORM, settings

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


async def _set_webhook() -> None:
    if not settings.WEBHOOK_URL:
        logger.warning("WEBHOOK_BASE_URL не задан — вебхук не установлен")
        return
    try:
        # drop_pending_updates НЕ ставим: на деплое в очереди лежат
        # deleted_business_messages — суть архива. Повторный set_webhook с тем же
        # URL очередь не трогает, зато обновляет secret и allowed_updates.
        await bot.set_webhook(
            url=settings.WEBHOOK_URL,
            secret_token=settings.WEBHOOK_SECRET,
            allowed_updates=_WEBHOOK_ALLOWED_UPDATES,
        )
    except Exception:
        logger.exception("Не удалось установить вебхук %s", settings.WEBHOOK_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    ops_sink.install()

    load_commands()
    # любой сбой БД, миграций или ключей = приложение не стартует (Render оставит прежнюю
    # версию), а администраторы получают причину в личку: данные важнее работы бота
    stage = "db"
    try:
        await Tortoise.init(config=TORTOISE_ORM)
        await ops_startup.check_fatal()
        stage = "vault"
        await vault.startup_check()
    except Exception as exc:
        await ops_startup.announce_failure(exc, stage=stage)
        raise

    await _set_webhook()

    # spawn: упавший цикл не исчезает молча, а попадает в лог и журнал ошибок
    _background_tasks.append(spawn(run_emoji_clock(bot), name="emoji_clock"))
    _background_tasks.append(spawn(run_retention_loop(), name="retention"))
    _background_tasks.append(spawn(run_reminders_loop(bot), name="reminders"))
    _background_tasks.append(spawn(run_scheduled_loop(bot), name="scheduled"))
    _background_tasks.append(spawn(ops_sink.run_writer(), name="ops_writer"))

    await mirror_manager.start_all()
    _background_tasks.append(spawn(userbot_manager.run(), name="userbot"))
    _background_tasks.append(spawn(ops_startup.report_started(), name="ops_started"))

    yield

    for task in _background_tasks:
        task.cancel()
    for task in _background_tasks:
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await task
    with contextlib.suppress(Exception):
        await ops_sink.flush_once()  # последние ошибки — пока БД ещё открыта
    ops_sink.uninstall()

    await mirror_manager.stop_all()
    await bot.session.close()
    await Tortoise.close_connections()


_docs_kwargs = (
    {}
    if settings.ENABLE_DOCS
    else {"docs_url": None, "redoc_url": None, "openapi_url": None}
)
app = FastAPI(lifespan=lifespan, **_docs_kwargs)

if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
app.add_middleware(
    RequestContextMiddleware
)  # внешний слой: request_id для всех ответов
mirror_dispatcher.update.outer_middleware(OpsContextMiddleware("mirror"))


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception):
    # в лог (и журнал ошибок) — с трассировкой; клиенту — только код и request_id
    logger.exception(
        "Необработанная ошибка API: %s %s", request.method, request.url.path
    )
    request_id = getattr(request.state, "request_id", None)
    # ответ обработчика идёт мимо RequestContextMiddleware (ServerErrorMiddleware снаружи)
    return JSONResponse(
        status_code=500,
        content={"code": ApiErrorCode.internal_error, "request_id": request_id},
        headers={"X-Request-ID": request_id or "", **cors_headers(request)},
    )


install_error_handlers(app)
app.include_router(setup_routers(), prefix="/api")
app.include_router(health_router)


@app.post(settings.WEBHOOK_PATH, include_in_schema=False)
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
        # только номер апдейта: текст чужих сообщений в логи Render не попадает
        logger.exception("Не удалось обработать апдейт %s", data.get("update_id"))
    return Response(status_code=200)


@app.post(f"{settings.MIRROR_WEBHOOK_PATH}/{{owner_id}}", include_in_schema=False)
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
            "Не удалось обработать апдейт зеркала owner_id=%s update_id=%s",
            owner_id,
            data.get("update_id"),
        )
    return Response(status_code=200)


@app.api_route("/", methods=["GET", "HEAD"], include_in_schema=False)
async def root():
    return {"status": "ok"}


@app.api_route("/health", methods=["GET", "HEAD"], include_in_schema=False)
async def health():
    return {"status": "ok"}
