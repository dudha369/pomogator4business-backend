"""Вход по QR: машина состояний на одного владельца. Без Telethon и aiogram.

Шлюз (`QrLoginGateway` из адаптера или подмена в тестах) даёт: `start() -> url`,
`wait(timeout) -> bool`, `recreate() -> url`, `password(pw)`, `identity()`,
`session_string()`, `close()`.

Состояние живёт в памяти процесса: при деплое вход надо начать заново (допустимо).
Пароль 2FA лежит в очереди только до `sign_in`, не логируется и не сохраняется."""

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from app.features.userbot import queries
from app.features.userbot.errors import (
    FloodWait,
    PasswordInvalid,
    PasswordNeeded,
    SessionRevoked,
)
from app.platform.tasks import spawn

logger = logging.getLogger("bot.userbot.login")

LOGIN_TTL = 180  # весь вход, секунд
QR_WAIT = 25  # QR-токен Telegram живёт около 30 с
MAX_PASSWORD_TRIES = 3
KEEP_FINISHED = 120  # сколько секунд показывать итог входа

STARTING, QR, PASSWORD, DONE, ERROR = "starting", "qr", "password", "done", "error"
ACTIVE_STATES = (STARTING, QR, PASSWORD)


@dataclass
class LoginFlow:
    owner_id: int
    consent_at: int
    state: str = STARTING
    qr_url: str | None = None
    error: str | None = (
        None  # код: invalid_password, flood, expired, storage, failed ...
    )
    started: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    task: asyncio.Task | None = None
    passwords: asyncio.Queue = field(default_factory=asyncio.Queue)
    qr_version: int = 0  # растёт при каждом новом QR (бот перерисовывает картинку)

    @property
    def active(self) -> bool:
        return self.state in ACTIVE_STATES

    def view(self) -> dict:
        return {
            "state": self.state,
            "qr_url": self.qr_url if self.state == QR else None,
            "error": self.error,
        }


flows: dict[int, LoginFlow] = {}


class _Stop(Exception):
    """Итог входа уже выставлен: дальше (сохранение) идти не надо."""


def get(owner_id: int) -> LoginFlow | None:
    flow = flows.get(owner_id)
    stale = (
        flow
        and not flow.active
        and flow.finished_at is not None
        and time.monotonic() - flow.finished_at > KEEP_FINISHED
    )
    if stale:
        flows.pop(owner_id, None)
        return None
    return flow


def _default_gateway():
    from app.features.userbot.telethon_adapter import QrLoginGateway

    return QrLoginGateway()


async def start(
    owner_id: int, consent_at: int, gateway_factory: Callable = _default_gateway
) -> LoginFlow:
    """Начать вход (или вернуть идущий). Предполагает, что доступность и согласие
    проверены вызывающим."""
    flow = get(owner_id)
    if flow and flow.active:
        return flow
    flow = LoginFlow(owner_id, consent_at)
    flows[owner_id] = flow
    flow.task = spawn(_run(flow, gateway_factory()), name=f"userbot-login-{owner_id}")
    return flow


async def submit_password(owner_id: int, password: str) -> bool:
    flow = get(owner_id)
    if not flow or flow.state != PASSWORD:
        return False
    flow.error = None
    flow.passwords.put_nowait(password)
    return True


async def cancel(owner_id: int) -> None:
    flow = flows.pop(owner_id, None)
    if flow and flow.task and not flow.task.done():
        flow.task.cancel()


def _finish(flow: LoginFlow, state: str, error: str | None = None) -> None:
    flow.state, flow.error, flow.finished_at = state, error, time.monotonic()


async def _run(flow: LoginFlow, gateway) -> None:
    try:
        await asyncio.wait_for(_login(flow, gateway), timeout=LOGIN_TTL)
    except _Stop:
        pass
    except TimeoutError:
        _finish(flow, ERROR, "expired")
    except asyncio.CancelledError:
        raise
    except FloodWait:
        _finish(flow, ERROR, "flood")
    except SessionRevoked:
        _finish(flow, ERROR, "failed")
    except Exception as exc:
        # тип ошибки без текста: в сообщении исключения не должно быть ничего лишнего
        logger.error("Вход юзербота не удался (%s)", type(exc).__name__)
        _finish(flow, ERROR, "failed")
    finally:
        await gateway.close()


async def _login(flow: LoginFlow, gateway) -> None:
    flow.qr_url = await gateway.start()
    flow.state, flow.qr_version = QR, flow.qr_version + 1
    try:
        while not await gateway.wait(QR_WAIT):
            flow.qr_url = await gateway.recreate()
            flow.qr_version += 1
    except PasswordNeeded:
        await _password_step(flow, gateway)
    await _save(flow, gateway)


async def _password_step(flow: LoginFlow, gateway) -> None:
    flow.state = PASSWORD
    for _ in range(MAX_PASSWORD_TRIES):
        password = await flow.passwords.get()
        try:
            await gateway.password(password)
            return
        except PasswordInvalid:
            flow.error = "invalid_password"
    _finish(flow, ERROR, "too_many_attempts")
    raise _Stop


async def _save(flow: LoginFlow, gateway) -> None:
    user_id, username = await gateway.identity()
    ok = await queries.save_session(
        flow.owner_id,
        gateway.session_string(),
        tg_user_id=user_id,
        username=username,
        consent_at=flow.consent_at,
    )
    if not ok:
        _finish(flow, ERROR, "storage")
        return
    _finish(flow, DONE)
    from app.features.userbot.manager import manager

    manager.nudge()
