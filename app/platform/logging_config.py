import logging
import re

from app.platform.log_context import ContextFilter

# Логи пишутся полностью (traceback тоже), но секреты из них вырезаются: токены бота,
# `key=…`, строки входа юзербота. Список точных значений берётся из настроек.
_PATTERNS = (
    (re.compile(r"\b\d{6,12}:[A-Za-z0-9_-]{30,}\b"), "<bot-token>"),
    (re.compile(r"tg://login\?token=\S+"), "tg://login?token=<hidden>"),
    (
        re.compile(
            r"(?i)\b(api_?key|api_?hash|token|secret|password|session|key)=[^\s&\"']+"
        ),
        r"\1=<hidden>",
    ),
)
_SECRET_SETTINGS = (
    "BOT_TOKEN",
    "DB_URL",
    "DATA_MASTER_KEYS",
    "WEBHOOK_SECRET_RAW",
    "HEALTH_SECRET",
    "TELEGRAM_API_HASH",
    "AI_API_KEY",
    "VT_API_KEY",
    "URLHAUS_AUTH_KEY",
    "SAFE_BROWSING_API_KEY",
)


def known_secrets() -> list[str]:
    from config import settings

    values = (str(getattr(settings, name, "") or "") for name in _SECRET_SETTINGS)
    return sorted({v for v in values if len(v) >= 6}, key=len, reverse=True)


def redact_secrets(text: str) -> str:
    for secret in known_secrets():
        text = text.replace(secret, "<secret>")
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text


class SecretsFormatter(logging.Formatter):
    """Обычный формат + вырезание секретов из итоговой строки (включая traceback)."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_secrets(super().format(record))


def configure_logging(level: int = logging.INFO) -> None:
    handler = logging.StreamHandler()
    handler.addFilter(ContextFilter())
    handler.setFormatter(
        SecretsFormatter(
            "%(asctime)s %(levelname)-8s %(name)s: %(ctx)s%(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logging.basicConfig(level=level, handlers=[handler], force=True)
