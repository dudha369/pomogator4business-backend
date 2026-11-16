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
    HISTORY_RETENTION_DAYS: int = 90
    ARCHIVE_RETENTION_DAYS: int = 0
    MESSAGE_LOG_KEEP: int = 20000

    AI_API_KEY: str = ""
    AI_MODEL: str = "claude-haiku-5-5"
    AI_API_URL: str = "https://api.anthropic.com/v1/messages"

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
                "db.models.echo",
                "db.models.message_log",
                "db.models.autoresponder",
                "app.features.mute.models",
                "db.models.story",
                "db.models.known_chat",
                "db.models.favorite_chat",
                "db.models.command_alias",
                "app.features.templates.models",
                "db.models.chat_flags",
                "db.models.ai",
                "app.features.reminders.models",
                "app.features.history.models",
                "app.features.archive.models",
                "app.features.profile.models",
                "db.models.mirror_bot",
                "db.models.clock",
                "db.models.emoji_status",
                "db.models.user_locale",
                "db.models.voice_effect",
                "db.models.scheduled_task",
                "app.features.games.models",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
}
