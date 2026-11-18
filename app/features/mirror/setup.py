import re
import time

from aiogram import Bot as AiogramBot

from app.features.alerts import service as alerts
from app.features.mirror.manager import MirrorStartError, mirror_manager
from app.features.mirror.queries import save_mirror
from app.platform.crypto import encrypt_token

_TOKEN_PATTERN = re.compile(r"^\d+:[A-Za-z0-9_-]{30,50}$")


class MirrorSetupError(Exception):
    def __init__(self, code: str):
        self.code = code  # "invalid_format" | "connection_failed" | "start_failed"
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

    # сначала запуск, потом запись в БД: при неудаче в БД не остаётся «подключённого»
    # зеркала, которого на деле нет, а прежнее рабочее зеркало не затрагивается
    try:
        await mirror_manager.start_mirror(owner_id, token, drop_pending=True)
    except MirrorStartError:
        raise MirrorSetupError("start_failed")
    await save_mirror(
        owner_id, encrypt_token(token), me.id, me.username, int(time.time())
    )
    await alerts.resolve(owner_id, "mirror_not_running")
    return me.username
