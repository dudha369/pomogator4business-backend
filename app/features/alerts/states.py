"""Живые проверки «проблема ещё есть?» для предупреждений-состояний.

Импорты внутри функций: `app.features.mirror.manager` тянет роутеры бота, а эта фича
подключается из `context.py` — на верхнем уровне получился бы цикл."""

from app.features.alerts.catalog import base_code


async def _mirror_not_running(owner_id: int) -> bool:
    from app.features.mirror.manager import mirror_manager
    from app.features.mirror.queries import get_mirror

    row = await get_mirror(owner_id)
    return bool(row and row["is_active"]) and not mirror_manager.is_running(owner_id)


async def _emoji_access_revoked(owner_id: int) -> bool:
    from app.features.emoji_clock.queries import is_emoji_status_granted

    return not await is_emoji_status_granted(owner_id)


async def _ai_no_key(owner_id: int) -> bool:
    from app.features.ai import service as ai
    from app.features.ai.queries import get_ai_settings

    settings = await get_ai_settings(owner_id)
    return bool(settings and settings["enabled"]) and not ai.is_configured()


async def _data_key_missing(owner_id: int) -> bool:
    from app.features.vault.service import failed_owners

    return owner_id in failed_owners


CHECKS = {
    "data_key_missing": _data_key_missing,
    "mirror_not_running": _mirror_not_running,
    "emoji_access_revoked": _emoji_access_revoked,
    "ai_no_key": _ai_no_key,
}


async def still_active(owner_id: int, code: str) -> bool:
    check = CHECKS.get(base_code(code))
    return await check(owner_id) if check else True
