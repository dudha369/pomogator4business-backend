import base64
import hashlib
import os

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import settings


def _derive_key() -> bytes:
    """Ключ шифрования для токенов зеркальных ботов.

    По умолчанию выводится детерминированно из settings.BOT_TOKEN — не нужно
    отдельно генерировать и хранить секрет, переживает рестарты и
    редеплои на эфемерной ФС. MIRROR_ENCRYPTION_KEY можно задать явно,
    если хочется отвязать ключ шифрования от settings.BOT_TOKEN — тогда ротация
    токена бота не потребует заново подключать зеркала (иначе, при
    выводе из settings.BOT_TOKEN, смена токена сделает уже сохранённые
    token_encrypted нерасшифровываемыми — придётся переподключить их
    через /mirror_connect).
    """
    env_key = os.getenv("MIRROR_ENCRYPTION_KEY")
    if env_key:
        return env_key.encode()

    digest = hashlib.sha256(
        f"pomogator4business-mirror:{settings.BOT_TOKEN}".encode()
    ).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_key())


def encrypt_token(token: str) -> bytes:
    return _fernet.encrypt(token.encode())


def decrypt_token(data: bytes) -> str:
    return _fernet.decrypt(data).decode()


# --- AEAD для содержимого в БД (см. app/features/vault) -------------------------------
NONCE_LEN = 12
KEY_LEN = 32


class CryptoError(Exception):
    """Не удалось расшифровать: неверный ключ, повреждённые данные или AAD."""


def new_key() -> bytes:
    return os.urandom(KEY_LEN)


def parse_master_keys(raw: str) -> dict[int, bytes]:
    """`"2:<base64url>,1:<base64url>"` -> {2: key, 1: key}. Первый — активный (его выбирает
    вызывающий). Пустая строка — ключей нет."""
    keys: dict[int, bytes] = {}
    for part in filter(None, (p.strip() for p in raw.split(","))):
        version, _, encoded = part.partition(":")
        try:
            key = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            number = int(version)
        except ValueError as exc:
            raise CryptoError("DATA_MASTER_KEYS: ожидается «версия:base64»") from exc
        if len(key) != KEY_LEN or not 0 < number < 32768 or number in keys:
            raise CryptoError(
                "DATA_MASTER_KEYS: ключ — 32 байта, версия 1..32767 без повторов"
            )
        keys[number] = key
    return keys


def aead_seal(key: bytes, aad: bytes, data: bytes) -> bytes:
    """nonce(12) + шифротекст с тегом. Случайный nonce безопасен для AES-GCM при
    нашем числе записей на ключ (лимит — порядка 2^32)."""
    nonce = os.urandom(NONCE_LEN)
    return nonce + AESGCM(key).encrypt(nonce, data, aad)


def aead_open(key: bytes, aad: bytes, blob: bytes) -> bytes:
    try:
        return AESGCM(key).decrypt(blob[:NONCE_LEN], blob[NONCE_LEN:], aad)
    except Exception as exc:  # InvalidTag, короткий blob
        raise CryptoError("не удалось расшифровать") from exc
