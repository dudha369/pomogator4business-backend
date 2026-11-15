import base64
import hashlib
import os

from cryptography.fernet import Fernet

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
