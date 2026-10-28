"""Резервная копия настроек владельца (JSON) и восстановление.

Нужна, чтобы перенести настройки на другую БД/окружение или откатить
случайные изменения. Данные подключения (архив, история) сюда не входят: при
переподключении бота они переносятся автоматически (core/connection_migration.py).
Ключей и токенов в копии нет."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from api.deps import require_connection, require_user
from core import database as db
from core.registry import registry

router = APIRouter()

FORMAT_VERSION = 1
_MAX_ITEMS = 500


@router.get("/backup/export")
async def export_backup(user: dict = Depends(require_user)):
    owner_id = user["id"]
    connection = await require_connection(owner_id)
    autoresponder = await db.get_autoresponder_settings(owner_id) or {}
    ai = await db.get_ai_settings(owner_id) or {}
    reminders = await db.get_reminder_settings(owner_id) or {}
    return {
        "version": FORMAT_VERSION,
        "prefix": connection["prefix"],
        "timezone_offset_minutes": await db.get_timezone_offset(owner_id),
        "disabled_modules": sorted(
            await db.list_disabled_modules(connection["connection_id"])
        ),
        "autoresponder": {
            k: autoresponder.get(k)
            for k in (
                "greeting_enabled",
                "greeting_text",
                "away_enabled",
                "away_text",
                "away_start_minutes",
                "away_end_minutes",
                "auto_read_enabled",
            )
        },
        "keywords": await db.list_keyword_replies(owner_id),
        "aliases": await db.list_command_aliases(owner_id),
        "templates": await db.list_templates(owner_id),
        "favorites": sorted(await db.list_favorite_chat_ids(owner_id)),
        "chat_flags": await db.list_chat_flags(owner_id),
        "reminders": {
            "enabled": bool(reminders.get("enabled", False)),
            "hours": reminders.get("hours", 4),
            "quiet_start_minutes": reminders.get("quiet_start_minutes"),
            "quiet_end_minutes": reminders.get("quiet_end_minutes"),
            "favorites_only": bool(reminders.get("favorites_only", False)),
        },
        "ai": {
            "enabled": bool(ai.get("enabled", False)),
            "mode": ai.get("mode", "draft"),
            "instructions": ai.get("instructions"),
            "history_messages": ai.get("history_messages", 10),
            "daily_limit": ai.get("daily_limit", 30),
        },
    }


class BackupImport(BaseModel):
    version: int
    prefix: str | None = Field(default=None, min_length=1, max_length=8)
    timezone_offset_minutes: int | None = Field(default=None, ge=-14 * 60, le=14 * 60)
    disabled_modules: list[str] | None = Field(default=None, max_length=_MAX_ITEMS)
    autoresponder: dict | None = None
    keywords: list[dict] | None = Field(default=None, max_length=_MAX_ITEMS)
    aliases: list[dict] | None = Field(default=None, max_length=_MAX_ITEMS)
    templates: list[dict] | None = Field(default=None, max_length=_MAX_ITEMS)
    favorites: list[int] | None = Field(default=None, max_length=_MAX_ITEMS)
    chat_flags: list[dict] | None = Field(default=None, max_length=_MAX_ITEMS)
    ai: dict | None = None
    reminders: dict | None = None


def _text(value, limit):
    return value[:limit] if isinstance(value, str) else None


@router.post("/backup/import")
async def import_backup(payload: BackupImport, user: dict = Depends(require_user)):
    """Накладывает копию поверх текущих настроек (слияние: совпадающие записи
    перезаписываются, остальные остаются). Некорректные записи пропускаются и
    считаются в `skipped`."""
    if payload.version != FORMAT_VERSION:
        raise HTTPException(status_code=422, detail="Unsupported backup version")

    owner_id = user["id"]
    connection = await require_connection(owner_id)
    applied, skipped = 0, 0

    if payload.prefix:
        await db.set_prefix(connection["connection_id"], payload.prefix)
        applied += 1
    if payload.timezone_offset_minutes is not None:
        await db.set_timezone_offset(owner_id, payload.timezone_offset_minutes)
        applied += 1

    if payload.disabled_modules is not None:
        known = set(registry.modules())
        for module in payload.disabled_modules:
            if module in known:
                await db.disable_module(connection["connection_id"], module)
                applied += 1
            else:
                skipped += 1

    if payload.autoresponder:
        src = payload.autoresponder
        fields = {}
        for key in ("greeting_enabled", "away_enabled", "auto_read_enabled"):
            if isinstance(src.get(key), bool):
                fields[key] = src[key]
        for key in ("greeting_text", "away_text"):
            if key in src and (src[key] is None or isinstance(src[key], str)):
                fields[key] = _text(src[key], 4096)
        for key in ("away_start_minutes", "away_end_minutes"):
            value = src.get(key)
            if value is None or (isinstance(value, int) and 0 <= value <= 1439):
                if key in src:
                    fields[key] = value
        # как в API: режим без текста не включаем
        for flag, text_key in (
            ("greeting_enabled", "greeting_text"),
            ("away_enabled", "away_text"),
        ):
            if fields.get(flag) and not (fields.get(text_key) or "").strip():
                fields[flag] = False
                skipped += 1
        await db.upsert_autoresponder_settings(owner_id, **fields)
        applied += 1

    for item in payload.keywords or []:
        keyword, reply = (
            _text(item.get("keyword"), 255),
            _text(item.get("reply_text"), 4096),
        )
        if keyword and keyword.strip() and reply and reply.strip():
            await db.add_keyword_reply(owner_id, keyword.strip().lower(), reply)
            applied += 1
        else:
            skipped += 1

    for item in payload.templates or []:
        name, text = _text(item.get("name"), 32), _text(item.get("text"), 4096)
        if name and name.strip() and " " not in name.strip() and text and text.strip():
            await db.save_template(owner_id, name.strip().lower(), text)
            applied += 1
        else:
            skipped += 1

    for item in payload.aliases or []:
        alias, command = _text(item.get("alias"), 32), _text(item.get("command"), 64)
        cmd = registry.find(command.lower()) if command else None
        if (
            alias
            and alias.strip()
            and " " not in alias.strip()
            and cmd
            and registry.find(alias.strip().lower()) is None
            and await db.get_command_alias(owner_id, alias.strip().lower()) is None
        ):
            await db.add_command_alias(owner_id, alias.strip().lower(), cmd.name)
            applied += 1
        else:
            skipped += 1

    for chat_id in payload.favorites or []:
        await db.set_favorite_chat(owner_id, chat_id, True)
        applied += 1

    for item in payload.chat_flags or []:
        chat_id = item.get("chat_id")
        if isinstance(chat_id, int):
            await db.set_chat_flags(
                owner_id,
                chat_id,
                no_autoreply=bool(item.get("no_autoreply")),
                no_ai=bool(item.get("no_ai")),
                no_remind=bool(item.get("no_remind")),
            )
            applied += 1
        else:
            skipped += 1

    if payload.reminders:
        src, fields = payload.reminders, {}
        if isinstance(src.get("enabled"), bool):
            fields["enabled"] = src["enabled"]
        if isinstance(src.get("favorites_only"), bool):
            fields["favorites_only"] = src["favorites_only"]
        if isinstance(src.get("hours"), int) and 1 <= src["hours"] <= 168:
            fields["hours"] = src["hours"]
        for key in ("quiet_start_minutes", "quiet_end_minutes"):
            value = src.get(key)
            if key in src and (
                value is None or (isinstance(value, int) and 0 <= value <= 1439)
            ):
                fields[key] = value
        await db.upsert_reminder_settings(owner_id, **fields)
        applied += 1

    if payload.ai:
        src, fields = payload.ai, {}
        if src.get("mode") in ("draft", "auto"):
            fields["mode"] = src["mode"]
        if isinstance(src.get("instructions"), str) or src.get("instructions") is None:
            fields["instructions"] = _text(src.get("instructions"), 2000)
        if (
            isinstance(src.get("history_messages"), int)
            and 0 <= src["history_messages"] <= 30
        ):
            fields["history_messages"] = src["history_messages"]
        if isinstance(src.get("daily_limit"), int) and 1 <= src["daily_limit"] <= 500:
            fields["daily_limit"] = src["daily_limit"]
        # включать ИИ из копии нельзя: это решение владельца на месте (ключ, риски, лимиты)
        await db.upsert_ai_settings(owner_id, **fields)
        applied += 1

    return {"applied": applied, "skipped": skipped}
