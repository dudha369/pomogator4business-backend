import re
import time

from aiogram import Bot as AiogramBot

from core import database as db
from core.crypto import encrypt_token
from core.mirror_manager import mirror_manager

_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{30,50}$")


class MirrorSetupError(Exception):
    def __init__(self, code: str):
        self.code = code  # "invalid_format" | "connection_failed"
        super().__init__(code)


async def connect_mirror(owner_id: int, token: str) -> str:
    """Проверяет и подключает токен зеркала. Возвращает username подключённого
    бота. И бот-команда /mirror, и веб-апп дёргают эту единую функцию —
    без дублирования логики проверки токена в двух местах."""
    token = token.strip()
    if not _TOKEN_PATTERN.match(token):
        raise MirrorSetupError("invalid_format")

    test_bot = AiogramBot(token=token)
    try:
        me = await test_bot.get_me()
    except Exception:
        raise MirrorSetupError("connection_failed")
    finally:
        await test_bot.session.close()

    await db.save_mirror(
        owner_id, encrypt_token(token), me.id, me.username, int(time.time())
    )
    await mirror_manager.start_mirror(owner_id, token)
    return me.username
