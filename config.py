import hashlib
from pathlib import Path

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).parent.absolute()


def _derive_webhook_secret(bot_token: str) -> str:
    digest = hashlib.sha256(f"pomogator4business-webhook:{bot_token}".encode())
    return digest.hexdigest()


class Settings(BaseSettings):
    BOT_TOKEN: str
    DB_URL: str

    WEBAPP_URL: str = ""
    VT_API_KEY: str = ""
    DEFAULT_PREFIX: str = "."

    WEBHOOK_PATH: str = "/webhook"
    MIRROR_WEBHOOK_PATH: str = "/webhook/mirror"
    WEBHOOK_BASE_URL: str = ""
    WEBHOOK_SECRET_RAW: str = Field(default="", alias="WEBHOOK_SECRET")

    # режим обслуживания: API отвечает 503 maintenance_mode (бот при этом работает)
    MAINTENANCE_MODE: bool = False
    # ограничение доступа к мини-приложению: id через запятую; пусто — доступ у всех
    ALLOWED_USER_IDS: str = ""

    # владелец проекта: id через запятую; безлимитный план (app/features/limits)
    ADMIN_USER_IDS: str = ""
    # лимиты планов: `метрика=число,…` (-1 — без лимита), см. app/features/limits/plans.py;
    # не названные метрики берут значения из кода
    PLAN_LIMITS_FREE: str = ""
    PLAN_LIMITS_PRO: str = ""
    PLAN_LIMITS_MAX: str = ""

    # пауза между одинаковыми предупреждениями владельцу (код из app/features/alerts/catalog.py)
    ALERT_COOLDOWN_HOURS: float = 6

    # Шифрование содержимого в БД (app/features/vault). Мастер-ключи: «версия:base64url»
    # через запятую, первый — активный: `2:<ключ>,1:<старый ключ>`. Сгенерировать:
    # `uv run python scripts/gen_master_key.py`. КОПИЮ хранить вне Render: потеряв ключ,
    # данные не восстановить. Пусто — шифрование выключено (только пока в БД нет шифротекста).
    DATA_MASTER_KEYS: str = ""
    # сколько последних записей архива просматривает поиск (шифротекст в SQL не ищется)
    ARCHIVE_SEARCH_SCAN: int = 3000
    # потолок строк на таблицу за один проход фонового шифрования старых данных
    VAULT_BACKFILL_MAX: int = 20000

    # Юзербот (app/features/userbot): один api_id приложения на всех. Получить на
    # my.telegram.org → API development tools. Не заданы — юзербот выключен.
    TELEGRAM_API_ID: int = 0
    TELEGRAM_API_HASH: str = ""
    # файлы юзербота (только в чатах, где включено «Файлы»): максимум на файл, байты
    USERBOT_MEDIA_MAX_BYTES: int = 20 * 1024 * 1024
    USERBOT_MEDIA_TIMEOUT: int = 120  # секунд на скачивание одного файла
    # список диалогов для экрана выбора чатов: сколько запрашиваем у Telegram
    USERBOT_DIALOGS_MAX: int = 300
    # массовое удаление: уведомления одного чата копятся BURST_WINDOW секунд;
    # больше BURST_THRESHOLD сообщений — вместо них одна сводка с числом
    USERBOT_BURST_WINDOW: float = 5
    USERBOT_BURST_THRESHOLD: int = 5

    KEEP_MEDIA_BYTES: bool = False
    ARCHIVE_RICH: bool = True
    # Какие типы файлов показывать в Rich. Голосовые по умолчанию обычные: на iPhone
    # Rich показывает их как аудио «Unknown track». Уберите тип из списка, если в Rich
    # он выглядит слишком крупным: он уйдёт обычным сообщением с подписью.
    ARCHIVE_RICH_KINDS: str = "photo,video,animation,audio,document"
    # Как показывать альбом в Rich: slideshow (листается) или collage (плитка).
    ARCHIVE_ALBUM_STYLE: str = "slideshow"
    MEDIA_RETENTION_DAYS: int = 14
    ARCHIVE_MEDIA_RETENTION_DAYS: int = 90
    # «окно слежения» (копия сообщений, чтобы показать удалённое/изменённое): 14 дней
    HISTORY_RETENTION_DAYS: int = 14
    # технические потолки на ПОДКЛЮЧЕНИЕ (бизнес-бот и юзербот отдельно); сверх них
    # самые старые строки окна обрезаются, 0 = без потолка. Защита базы от шумных чатов.
    HISTORY_MAX_PER_CONNECTION: int = 100000
    HISTORY_MEDIA_MAX_MB: int = 200
    ARCHIVE_RETENTION_DAYS: int = 0
    MESSAGE_LOG_KEEP: int = 20000
    # записи журнала .del/.panic старше этого срока удаляются (0 = только лимит MESSAGE_LOG_KEEP)
    MESSAGE_LOG_RETENTION_DAYS: int = 30
    # сколько строк history за проход очистки избавлять от ненужного raw_json (0 = выключено)
    RAW_JSON_SCRUB_BATCH: int = 2000

    # Linkscan (app/features/linkscan): провайдеры без ключа пропускаются
    URLHAUS_AUTH_KEY: str = ""  # бесплатный ключ abuse.ch (auth.abuse.ch)
    SAFE_BROWSING_API_KEY: str = (
        ""  # Google Safe Browsing v4 (только некоммерческое использование)
    )
    # VirusTotal (ключ — VT_API_KEY выше): публичный API 4/мин, 500/сутки, только некоммерческий.
    # Для публичного сервиса выключить: LINKSCAN_VT_ENABLED=false
    LINKSCAN_VT_ENABLED: bool = True
    LINKSCAN_VT_DAILY_LIMIT: int = (
        400  # с запасом: тот же ключ использует команда .check
    )
    LINKSCAN_CACHE_TTL_HOURS: float = 24
    LINKSCAN_MAX_LINKS: int = 5  # ссылок из одного сообщения

    AI_API_KEY: str = ""
    AI_MODEL: str = "claude-haiku-5-5"
    AI_API_URL: str = "https://api.anthropic.com/v1/messages"

    # Наблюдаемость (app/features/ops): оповещения администраторам (ADMIN_USER_IDS)
    HEALTH_SECRET: str = ""  # заголовок X-Health-Secret для GET /health/deep; пусто — только initData админа
    OPS_REPEAT_MINUTES: int = 60  # повтор той же ошибки — не чаще
    OPS_BURST_THRESHOLD: int = 20  # событий за 5 минут = «всплеск»
    OPS_MAX_PER_HOUR: int = 10  # потолок обычных оповещений в час
    ERROR_EVENTS_RETENTION_DAYS: int = 30
    SKIP_MIGRATION_CHECK: bool = (
        False  # аварийный выход: не сверять миграции при старте
    )
    RENDER_GIT_COMMIT: str = ""  # Render отдаёт сам
    BUILD_SHA: str = ""  # запасной источник версии сборки

    # Документация API (/docs, /openapi.json) — только для разработки
    ENABLE_DOCS: bool = False

    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    CORS_ORIGINS_RAW: str = Field(default="", alias="CORS_ORIGINS")

    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @computed_field
    @property
    def WEBHOOK_URL(self) -> str | None:
        if not self.WEBHOOK_BASE_URL:
            return None
        return f"{self.WEBHOOK_BASE_URL}{self.WEBHOOK_PATH}"

    @computed_field
    @property
    def WEBHOOK_SECRET(self) -> str:
        return self.WEBHOOK_SECRET_RAW or _derive_webhook_secret(self.BOT_TOKEN)

    @property
    def BUILD(self) -> str:
        return (self.RENDER_GIT_COMMIT or self.BUILD_SHA)[:7] or "unknown"

    @property
    def USERBOT_CONFIGURED(self) -> bool:
        return bool(self.TELEGRAM_API_ID and self.TELEGRAM_API_HASH)

    @computed_field
    @property
    def CORS_ORIGINS(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.CORS_ORIGINS_RAW.split(",")
            if origin.strip()
        ]


settings = Settings()

TORTOISE_ORM = {
    "connections": {"default": settings.DB_URL},
    "apps": {
        "models": {
            "models": [
                "db.models.connection",
                "db.models.module_settings",
                "app.features.echo.models",
                "app.features.autoresponder.models",
                "app.features.mute.models",
                "app.features.ops.models",
                "app.features.story.models",
                "app.features.chats.models",
                "db.models.command_alias",
                "app.features.templates.models",
                "app.features.ai.models",
                "app.features.reminders.models",
                "app.features.history.models",
                "app.features.archive.models",
                "app.features.profile.models",
                "app.features.mirror.models",
                "app.features.emoji_clock.models",
                "db.models.user_locale",
                "app.features.voice_effects.models",
                "app.features.scheduled.models",
                "app.features.games.models",
                "app.features.alerts.models",
                "app.features.linkscan.models",
                "app.features.vault.models",
                "app.features.userbot.models",
                "app.features.limits.models",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
}
