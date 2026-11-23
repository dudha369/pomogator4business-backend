"""Блокировка «клиенты юзербота запущены только в одном процессе».

Render при деплое на время держит два процесса; одна сессия Telegram в двух процессах
может быть аннулирована (AUTH_KEY_DUPLICATED). Поэтому клиенты стартуют только под
advisory lock Postgres на ВЫДЕЛЕННОМ соединении: оно живёт, пока держится блокировка, а
сервер снимает её сам, если процесс умер.

Нужно прямое подключение к Postgres: через pgbouncer в режиме transaction pooling
(`-pooler` в имени хоста Neon) блокировка уровня сессии ненадёжна.
"""

import asyncio
import hashlib
import logging
from urllib.parse import parse_qs, unquote, urlsplit

from config import settings

logger = logging.getLogger("bot.userbot.lock")

# стабильный bigint-ключ: одна блокировка на всё приложение
LOCK_KEY = int.from_bytes(
    hashlib.sha256(b"pomogator4business:userbot").digest()[:8], "big", signed=True
)
_CONNECT_TIMEOUT = 10


def _pg_kwargs(dsn: str) -> dict:
    """`asyncpg://u:p@host/db?ssl=true` (формат Tortoise) -> аргументы asyncpg.connect."""
    parts = urlsplit(dsn)
    query = parse_qs(parts.query)
    ssl = (query.get("ssl") or query.get("sslmode") or [""])[0].lower()
    return {
        "host": parts.hostname,
        "port": parts.port or 5432,
        "user": unquote(parts.username or "") or None,
        "password": unquote(parts.password or "") or None,
        "database": parts.path.lstrip("/") or None,
        "ssl": True if ssl in ("true", "1", "require", "verify-full") else None,
        "timeout": _CONNECT_TIMEOUT,
        "command_timeout": _CONNECT_TIMEOUT,
    }


def is_postgres(dsn: str) -> bool:
    return dsn.startswith(("asyncpg://", "postgres://", "postgresql://"))


class PgAdvisoryLock:
    def __init__(self, dsn: str | None = None):
        self._dsn = dsn or settings.DB_URL
        self._conn = None
        self.lost = asyncio.Event()  # соединение потеряно — блокировки больше нет

    async def acquire(self) -> bool:
        import asyncpg

        self.lost.clear()
        try:
            conn = await asyncpg.connect(**_pg_kwargs(self._dsn))
        except Exception as exc:
            logger.warning(
                "Блокировка юзербота: нет соединения (%s)", type(exc).__name__
            )
            return False
        try:
            got = await conn.fetchval("SELECT pg_try_advisory_lock($1)", LOCK_KEY)
        except Exception:
            await conn.close()
            return False
        if not got:
            await conn.close()
            return False
        conn.add_termination_listener(lambda _c: self.lost.set())
        self._conn = conn
        return True

    async def check(self) -> bool:
        """Heartbeat: соединение живо (и не даёт ему простаивать)."""
        if self._conn is None or self.lost.is_set():
            return False
        try:
            await self._conn.fetchval("SELECT 1")
        except Exception:
            self.lost.set()
            return False
        return True

    async def release(self) -> None:
        conn, self._conn = self._conn, None
        if conn is None:
            return
        try:
            if not conn.is_closed():
                await conn.execute("SELECT pg_advisory_unlock($1)", LOCK_KEY)
        except Exception:
            logger.debug("pg_advisory_unlock не выполнен", exc_info=True)
        finally:
            await conn.close(timeout=2)


class LocalLock:
    """Для SQLite (тесты, локальный запуск): исключение только внутри процесса."""

    _held = False

    def __init__(self):
        self.lost = asyncio.Event()
        self._mine = False

    async def acquire(self) -> bool:
        if LocalLock._held:
            return False
        LocalLock._held = self._mine = True
        self.lost.clear()
        return True

    async def check(self) -> bool:
        return self._mine and not self.lost.is_set()

    async def release(self) -> None:
        if self._mine:
            LocalLock._held = self._mine = False


def make_lock() -> PgAdvisoryLock | LocalLock:
    return PgAdvisoryLock() if is_postgres(settings.DB_URL) else LocalLock()
