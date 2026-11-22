"""Решения и запросы фичи «alerts» (без aiogram)."""

import time

from app.features.alerts.catalog import (
    MAX_CODE_LEN,
    MAX_DETAIL_LEN,
    cooldown_seconds,
    spec_for,
)
from app.features.alerts.models import Alert, AlertMute
from app.features.vault import service as vault

TABLE = "alerts"


async def _open(alert: Alert | None) -> Alert | None:
    """Расшифровывает `details` у загруженной строки (в БД они — шифротекст)."""
    if alert is not None and alert.enc_ver is not None:
        row = await vault.open_row(
            TABLE, alert.owner_id, {"details": alert.details, "enc_ver": alert.enc_ver}
        )
        alert.details = row["details"] or {}
    return alert


def clean_details(details: dict) -> dict[str, str]:
    return {str(k): str(v)[:MAX_DETAIL_LEN] for k, v in details.items()}


async def is_muted(owner_id: int, code: str) -> bool:
    return await AlertMute.filter(owner_id=owner_id, code=code).exists()


async def record(
    owner_id: int, code: str, details: dict, now: int | None = None
) -> Alert | None:
    """Зафиксировать предупреждение. Возвращает строку, если владельцу нужно написать
    сейчас; None — код отключён («Больше не показывать») или ещё идёт пауза.

    Событие при каждом повторе увеличивает счётчик. Состояние при повторе в паузе
    ничего не пишет: его сообщают из горячих путей (например, на каждое сообщение)."""
    if len(code) > MAX_CODE_LEN:
        raise ValueError(f"alert code too long: {code!r}")
    spec = spec_for(code)
    if await is_muted(owner_id, code):
        return None

    now = int(time.time()) if now is None else now
    details = clean_details(details)
    # при сбое шифрования подробности не пишем (открытый текст в БД не попадает)
    sealed = await vault.seal_values(TABLE, owner_id, {"details": details}) or {
        "details": {}
    }
    alert, created = await Alert.get_or_create(
        owner_id=owner_id,
        code=code,
        defaults={
            "kind": spec.kind,
            "created_at": now,
            "last_at": now,
            "notified_at": now,
            **sealed,
        },
    )
    if created:
        alert.details = details
        return alert
    await _open(alert)

    due = now - alert.notified_at >= cooldown_seconds(code)
    if spec.kind == "state" and not due:
        return None
    # счётчик без атомарности: гонка двух повторов может ошибиться на единицу — не важно
    alert.count += 1
    alert.last_at = now
    alert.details = sealed["details"]
    alert.enc_ver = sealed.get("enc_ver")
    fields = ["count", "last_at", "details", "enc_ver"]
    if due:
        alert.notified_at = now
        alert.dismissed = False
        fields += ["notified_at", "dismissed"]
    await alert.save(update_fields=fields)
    alert.details = details
    return alert if due else None


async def resolve(owner_id: int, code: str) -> None:
    """Проблема устранена: убрать из списка (пауза для следующего сбоя сбрасывается)."""
    await Alert.filter(owner_id=owner_id, code=code).delete()


async def list_active(owner_id: int) -> list[Alert]:
    """Видимые предупреждения. Строки-состояния, которые уже не соответствуют
    действительности, удаляются здесь же."""
    from app.features.alerts.states import still_active

    rows = await Alert.filter(owner_id=owner_id).order_by("-last_at")
    result = []
    for row in rows:
        await _open(row)
        if row.kind == "state" and not await still_active(owner_id, row.code):
            await row.delete()
        elif not row.dismissed:
            result.append(row)
    return result


async def get_alert(owner_id: int, alert_id: int) -> Alert | None:
    return await _open(await Alert.filter(owner_id=owner_id, id=alert_id).first())


async def dismiss(owner_id: int, alert_id: int) -> bool:
    return bool(
        await Alert.filter(owner_id=owner_id, id=alert_id).update(dismissed=True)
    )


async def mute(owner_id: int, alert_id: int) -> str | None:
    """«Больше не показывать». Возвращает код или None, если такого предупреждения нет."""
    alert = await get_alert(owner_id, alert_id)
    if not alert:
        return None
    await AlertMute.get_or_create(owner_id=owner_id, code=alert.code)
    await alert.delete()
    return alert.code


async def unmute(owner_id: int, code: str) -> bool:
    return bool(await AlertMute.filter(owner_id=owner_id, code=code).delete())


async def list_muted(owner_id: int) -> list[str]:
    return (
        await AlertMute.filter(owner_id=owner_id)
        .order_by("code")
        .values_list("code", flat=True)
    )
