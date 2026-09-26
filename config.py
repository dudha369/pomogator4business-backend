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
    WEBHOOK_BASE_URL: str = ""
    WEBHOOK_SECRET_RAW: str = Field(default="", alias="WEBHOOK_SECRET")

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
                "db.models.mute",
                "db.models.story",
                "db.models.known_chat",
                "db.models.message_history",
                "db.models.archive_log",
                "db.models.profile_backup",
                "db.models.mirror_bot",
                "db.models.clock",
                "db.models.emoji_status",
                "db.models.user_locale",
                "db.models.voice_effect",
                "db.models.ttt",
                "db.models.wordle",
                "db.models.checkers",
                "db.models.minesweeper",
                "db.models.guess",
                "db.models.city",
                "db.models.hangman",
                "db.models.g2048",
                "aerich.models",
            ],
            "default_connection": "default",
        }
    },
}
