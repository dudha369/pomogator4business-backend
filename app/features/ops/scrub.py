"""Безопасное описание исключения для журнала и оповещений. Без БД и aiogram.

Основа — БЕЛЫЙ список, а не поиск секретов: в `sample` попадают только кадры стека
(файл, строка, функция) и тип исключения. Текст исключения включается лишь для известных
безопасных типов: у pydantic ValidationError и ошибок Postgres в тексте стоят значения
полей, то есть чужие сообщения. Локальные переменные и args не берутся никогда.
Поверх — второй слой: вырезание токенов, `key=…`, URL с query, длинных blob-строк."""

import hashlib
import re
import traceback
from dataclasses import dataclass
from pathlib import Path

from app.platform.logging_config import redact_secrets
from config import ROOT_DIR

MAX_FRAMES = 12
MAX_SAMPLE = 2000
MAX_MESSAGE = 120

# имена классов в MRO, чей текст безопасен и полезен
_SAFE_MESSAGE = {"TelegramAPIError", "TimeoutError", "ConnectionError", "VaultError"}
# БД, шифрование: оповещение критичное (не глушится)
_CRITICAL = {
    "OperationalError",
    "DBConnectionError",
    "InterfaceError",
    "ConnectionDoesNotExistError",
    "CannotConnectNowError",
    "VaultError",
    "CryptoError",
}

_URL_QUERY = re.compile(r"(https?://[^\s?#]+)\?\S+")
_BLOB = re.compile(r"[A-Za-z0-9+/_-]{40,}={0,2}")


@dataclass(frozen=True)
class Described:
    kind: str  # короткое имя класса
    place: str  # файл:строка функция (для людей)
    fingerprint_key: str  # файл:функция (стабильно между деплоями)
    sample: str
    critical: bool


def scrub_text(text: str) -> str:
    text = redact_secrets(text)
    text = _URL_QUERY.sub(r"\1?<query>", text)
    return _BLOB.sub("<blob>", text)


def fingerprint(component: str, kind_full: str, fingerprint_key: str) -> str:
    raw = f"{component}|{kind_full}|{fingerprint_key}"
    return hashlib.sha1(raw.encode()).hexdigest()


def _rel(path: str) -> tuple[str, bool]:
    """(путь без абсолютной части, это код проекта). Пакеты — `пакет/файл.py`."""
    try:
        rel = Path(path).resolve().relative_to(ROOT_DIR)
    except (ValueError, OSError):
        rel = None
    if rel is not None and not str(rel).startswith(".venv"):
        return rel.as_posix(), True
    path = path.replace("\\", "/")  # Windows: пути пакетов с обратными слэшами
    marker = "site-packages/"
    return (
        path.split(marker, 1)[1] if marker in path else path.rsplit("/", 1)[-1]
    ), False


def _message(exc: BaseException) -> str | None:
    names = {c.__name__ for c in type(exc).__mro__}
    if not names & _SAFE_MESSAGE:
        return None
    text = getattr(exc, "message", None) or str(exc)
    return scrub_text(text.replace("\n", " "))[:MAX_MESSAGE]


def describe(exc: BaseException) -> Described:
    frames = traceback.extract_tb(exc.__traceback__)[-MAX_FRAMES:]
    lines = []
    inner = None  # последний кадр проекта; иначе просто последний
    for fr in frames:
        rel, is_project = _rel(fr.filename)
        lines.append(f"{rel}:{fr.lineno} in {fr.name}")
        if is_project:
            inner = (rel, fr.lineno, fr.name)
    if inner is None and frames:
        fr = frames[-1]
        inner = (_rel(fr.filename)[0], fr.lineno, fr.name)
    rel, lineno, func = inner or ("?", 0, "?")

    kind = type(exc).__name__
    head = kind
    message = _message(exc)
    head += f": {message}" if message else " (текст скрыт)"
    cause = exc.__cause__ or exc.__context__
    if cause is not None:
        head += f"\n← {type(cause).__name__}"
    sample = scrub_text(head + "\n" + "\n".join(lines))[:MAX_SAMPLE]

    names = {c.__name__ for c in type(exc).__mro__}
    if cause is not None:
        names |= {c.__name__ for c in type(cause).__mro__}
    return Described(
        kind=kind[:80],
        place=f"{rel}:{lineno} {func}"[:160],
        fingerprint_key=f"{rel}:{func}",
        sample=sample,
        critical=bool(names & _CRITICAL),
    )
