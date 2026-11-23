"""Запросы к `userbot_sessions`. Строка сессии шифруется и читается ТОЛЬКО здесь (vault)."""

import time

from app.features.userbot.models import UserbotSession
from app.features.vault import service as vault

TABLE = "userbot_sessions"
_PUBLIC = (
    "owner_id",
    "status",
    "connected",
    "tg_user_id",
    "tg_username",
    "consent_at",
    "created_at",
    "last_error",
)


async def get_info(owner_id: int) -> dict | None:
    """Строка без самой сессии."""
    rows = await UserbotSession.filter(owner_id=owner_id).values(*_PUBLIC)
    return rows[0] if rows else None


async def get_session_string(owner_id: int) -> str | None:
    rows = await UserbotSession.filter(owner_id=owner_id).values("session", "enc_ver")
    if not rows or rows[0]["session"] is None:
        return None
    return (await vault.open_row(TABLE, owner_id, rows[0]))["session"]


async def save_session(
    owner_id: int,
    session: str,
    *,
    tg_user_id: int,
    username: str | None,
    consent_at: int,
) -> bool:
    """Новая или заменённая сессия. False — не записано (шифрование выключено или
    сломалось): открытая строка сессии в БД недопустима."""
    if not vault.enabled():
        return False
    sealed = await vault.seal_values(TABLE, owner_id, {"session": session})
    if sealed is None or sealed.get("enc_ver") is None:
        return False
    await UserbotSession.update_or_create(
        owner_id=owner_id,
        defaults={
            **sealed,
            "status": "active",
            "connected": False,
            "tg_user_id": tg_user_id,
            "tg_username": username,
            "consent_at": consent_at,
            "created_at": int(time.time()),
            "last_error": None,
        },
    )
    return True


async def update_session_string(owner_id: int, session: str) -> None:
    """Строка изменилась (смена DC): перезаписываем, только если сессия ещё жива."""
    sealed = await vault.seal_values(TABLE, owner_id, {"session": session})
    if sealed is None or sealed.get("enc_ver") is None:
        return
    await UserbotSession.filter(owner_id=owner_id, status="active").update(**sealed)


async def set_status(owner_id: int, status: str, *, error: str | None = None) -> None:
    fields: dict = {"status": status, "last_error": error}
    if status != "active":
        fields["connected"] = False
    if status == "revoked":
        fields.update(session=None, enc_ver=None)  # мёртвая строка не нужна
    await UserbotSession.filter(owner_id=owner_id).update(**fields)


async def set_connected(
    owner_id: int, connected: bool, error: str | None = None
) -> None:
    await UserbotSession.filter(owner_id=owner_id).update(
        connected=connected, last_error=error
    )


async def delete_session(owner_id: int) -> None:
    await UserbotSession.filter(owner_id=owner_id).delete()


async def owners_with_status(status: str) -> list[int]:
    return await UserbotSession.filter(status=status).values_list("owner_id", flat=True)
