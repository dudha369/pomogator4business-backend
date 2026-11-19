from datetime import UTC, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from tortoise import fields
from tortoise.models import Model

from app.platform.ttl_cache import clear_all, ttl_cache

_DEFAULT_TZ_OFFSET_MINUTES = 180


class UserLocale(Model):
    owner_id = fields.BigIntField(pk=True, generated=False)
    locale = fields.CharField(max_length=8, default="ru")
    language_chosen = fields.BooleanField(default=False)
    # фиксированное смещение: запасной вариант и ручной выбор в приложении
    timezone_offset_minutes = fields.IntField(default=_DEFAULT_TZ_OFFSET_MINUTES)
    # IANA-имя (Europe/Kyiv): если задано, смещение считается на лету с учётом перехода на летнее время
    timezone = fields.CharField(max_length=64, null=True)

    class Meta:
        table = "user_locale"


async def has_chosen_locale(owner_id):
    rows = await UserLocale.filter(owner_id=owner_id).values("language_chosen")
    return bool(rows and rows[0]["language_chosen"])


@ttl_cache
async def get_locale(owner_id):
    rows = await UserLocale.filter(owner_id=owner_id).values("locale")
    return rows[0]["locale"] if rows else "ru"


async def set_locale(owner_id, locale):
    await UserLocale.update_or_create(
        owner_id=owner_id, defaults={"locale": locale, "language_chosen": True}
    )
    clear_all()


def is_valid_timezone(name) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError, OSError):
        return False
    return True


def effective_offset(timezone_name, fallback_minutes, now=None) -> int:
    """Текущее смещение от UTC в минутах: из IANA-имени (DST), иначе фиксированное."""
    if timezone_name and is_valid_timezone(timezone_name):
        moment = now or datetime.now(UTC)
        delta = moment.astimezone(ZoneInfo(timezone_name)).utcoffset()
        return int(delta.total_seconds() // 60)
    return fallback_minutes


async def get_timezone_offsets_for(owner_ids):
    """{owner_id: текущее смещение в минутах}; для неизвестных — значение по умолчанию."""
    if not owner_ids:
        return {}
    rows = await UserLocale.filter(owner_id__in=owner_ids).values(
        "owner_id", "timezone", "timezone_offset_minutes"
    )
    found = {
        r["owner_id"]: effective_offset(r["timezone"], r["timezone_offset_minutes"])
        for r in rows
    }
    return {oid: found.get(oid, _DEFAULT_TZ_OFFSET_MINUTES) for oid in owner_ids}


async def get_timezone_offset(owner_id):
    return (await get_timezone_offsets_for([owner_id]))[owner_id]


async def get_timezone_name(owner_id):
    rows = await UserLocale.filter(owner_id=owner_id).values("timezone")
    return rows[0]["timezone"] if rows else None


async def set_timezone_offset(owner_id, offset_minutes):
    """Ручной выбор смещения сбрасывает IANA-имя: пользователь так решил."""
    await UserLocale.update_or_create(
        owner_id=owner_id,
        defaults={"timezone_offset_minutes": offset_minutes, "timezone": None},
    )


async def set_timezone_name(owner_id, name):
    """Сохраняет IANA-имя и заодно его текущее смещение (запас на случай сбоя tzdata)."""
    await UserLocale.update_or_create(
        owner_id=owner_id,
        defaults={
            "timezone": name,
            "timezone_offset_minutes": effective_offset(
                name, _DEFAULT_TZ_OFFSET_MINUTES
            ),
        },
    )
