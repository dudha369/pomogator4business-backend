from tortoise import fields
from tortoise.models import Model

_DEFAULT_TZ_OFFSET_MINUTES = 180


class UserLocale(Model):
    owner_id = fields.BigIntField(pk=True, generated=False)
    locale = fields.CharField(max_length=8, default="ru")
    language_chosen = fields.BooleanField(default=False)
    timezone_offset_minutes = fields.IntField(default=_DEFAULT_TZ_OFFSET_MINUTES)

    class Meta:
        table = "user_locale"


async def has_chosen_locale(owner_id):
    rows = await UserLocale.filter(owner_id=owner_id).values("language_chosen")
    return bool(rows and rows[0]["language_chosen"])


async def get_locale(owner_id):
    rows = await UserLocale.filter(owner_id=owner_id).values("locale")
    return rows[0]["locale"] if rows else "ru"


async def set_locale(owner_id, locale):
    await UserLocale.update_or_create(
        owner_id=owner_id, defaults={"locale": locale, "language_chosen": True}
    )


async def get_timezone_offset(owner_id):
    rows = await UserLocale.filter(owner_id=owner_id).values("timezone_offset_minutes")
    return rows[0]["timezone_offset_minutes"] if rows else _DEFAULT_TZ_OFFSET_MINUTES


async def set_timezone_offset(owner_id, offset_minutes):
    await UserLocale.update_or_create(
        owner_id=owner_id, defaults={"timezone_offset_minutes": offset_minutes}
    )


async def get_timezone_offsets_for(owner_ids):
    if not owner_ids:
        return {}
    rows = await UserLocale.filter(owner_id__in=owner_ids).values(
        "owner_id", "timezone_offset_minutes"
    )
    offsets = {r["owner_id"]: r["timezone_offset_minutes"] for r in rows}
    return {oid: offsets.get(oid, _DEFAULT_TZ_OFFSET_MINUTES) for oid in owner_ids}
