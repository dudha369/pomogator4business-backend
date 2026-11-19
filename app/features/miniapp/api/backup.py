"""Резервная копия настроек владельца (JSON) и восстановление.

Нужна, чтобы перенести настройки на другую БД/окружение или откатить
случайные изменения. Данные подключения (архив, история) сюда не входят: при
переподключении бота они переносятся автоматически (app/features/connection/service.py).
Ключей и токенов в копии нет."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.features.ai.queries import get_ai_settings, upsert_ai_settings
from app.features.autoresponder.api import MAX_KEYWORDS
from app.features.autoresponder.queries import (
    add_keyword_reply,
    get_autoresponder_settings,
    list_keyword_replies,
    upsert_autoresponder_settings,
)
from app.features.chats.queries import (
    list_chat_flags,
    list_favorite_chat_ids,
    set_chat_flags,
    set_favorite_chat,
)
from app.features.miniapp.api.aliases import MAX_ALIASES_PER_OWNER
from app.features.reminders.service import (
    get_reminder_settings,
    upsert_reminder_settings,
)
from app.features.templates.api import MAX_TEMPLATES
from app.features.templates.service import (
    count_templates,
    get_template,
    list_templates,
    save_template,
)
from app.platform.api.deps import require_connection, require_user
from app.platform.api.schemas import (
    AiCore,
    ChatFlags,
    CommandAlias,
    KeywordReply,
    RemindersSettings,
    Template,
)
from app.platform.telegram.registry import registry
from app.platform.utils import is_valid_prefix
from db.models.command_alias import (
    add_command_alias,
    count_command_aliases,
    get_command_alias,
    list_command_aliases,
)
from db.models.connection import set_prefix
from db.models.module_settings import disable_module, list_disabled_modules
from db.models.user_locale import (
    get_timezone_name,
    get_timezone_offset,
    is_valid_timezone,
    set_timezone_name,
    set_timezone_offset,
)

router = APIRouter()

FORMAT_VERSION = 1
_MAX_ITEMS = 500


class AutoresponderBackup(BaseModel):
    # у владельца без сохранённых настроек все поля null
    greeting_enabled: bool | None
    greeting_text: str | None
    away_enabled: bool | None
    away_text: str | None
    away_start_minutes: int | None
    away_end_minutes: int | None
    auto_read_enabled: bool | None


class BackupExport(BaseModel):
    version: int
    prefix: str
    timezone_offset_minutes: int
    timezone: str | None
    disabled_modules: list[str]
    autoresponder: AutoresponderBackup
    keywords: list[KeywordReply]
    aliases: list[CommandAlias]
    templates: list[Template]
    favorites: list[int]
    chat_flags: list[ChatFlags]
    reminders: RemindersSettings
    ai: AiCore


class BackupImportResult(BaseModel):
    applied: int
    skipped: int


@router.get("/backup/export", response_model=BackupExport)
async def export_backup(user: dict = Depends(require_user)):
    owner_id = user["id"]
    connection = await require_connection(owner_id)
    autoresponder = await get_autoresponder_settings(owner_id) or {}
    ai = await get_ai_settings(owner_id) or {}
    reminders = await get_reminder_settings(owner_id) or {}
    return {
        "version": FORMAT_VERSION,
        "prefix": connection["prefix"],
        "timezone_offset_minutes": await get_timezone_offset(owner_id),
        "timezone": await get_timezone_name(owner_id),
        "disabled_modules": sorted(
            await list_disabled_modules(connection["connection_id"])
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
        "keywords": await list_keyword_replies(owner_id),
        "aliases": await list_command_aliases(owner_id),
        "templates": await list_templates(owner_id),
        "favorites": sorted(await list_favorite_chat_ids(owner_id)),
        "chat_flags": await list_chat_flags(owner_id),
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
    prefix: str | None = Field(default=None, max_length=8)
    timezone_offset_minutes: int | None = Field(default=None, ge=-14 * 60, le=14 * 60)
    timezone: str | None = Field(default=None, max_length=64)
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


@router.post("/backup/import", response_model=BackupImportResult)
async def import_backup(payload: BackupImport, user: dict = Depends(require_user)):
    """Накладывает копию поверх текущих настроек (слияние: совпадающие записи
    перезаписываются, остальные остаются). Некорректные записи пропускаются и
    считаются в `skipped`."""
    if payload.version != FORMAT_VERSION:
        raise HTTPException(status_code=422, detail="Unsupported backup version")

    owner_id = user["id"]
    connection = await require_connection(owner_id)
    applied, skipped = 0, 0

    if payload.prefix is not None:
        if is_valid_prefix(payload.prefix):
            await set_prefix(connection["connection_id"], payload.prefix)
            applied += 1
        else:
            skipped += 1
    if payload.timezone is not None:
        # IANA-имя важнее смещения: оно переживает переход на летнее время
        if is_valid_timezone(payload.timezone):
            await set_timezone_name(owner_id, payload.timezone)
            applied += 1
        else:
            skipped += 1
    elif payload.timezone_offset_minutes is not None:
        await set_timezone_offset(owner_id, payload.timezone_offset_minutes)
        applied += 1

    if payload.disabled_modules is not None:
        known = set(registry.modules())
        for module in payload.disabled_modules:
            if module in known:
                await disable_module(connection["connection_id"], module)
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
            valid = value is None or (isinstance(value, int) and 0 <= value <= 1439)
            if valid and key in src:
                fields[key] = value
        # как в API: режим без текста не включаем
        for flag, text_key in (
            ("greeting_enabled", "greeting_text"),
            ("away_enabled", "away_text"),
        ):
            if fields.get(flag) and not (fields.get(text_key) or "").strip():
                fields[flag] = False
                skipped += 1
        await upsert_autoresponder_settings(owner_id, **fields)
        applied += 1

    # те же квоты, что в обычных эндпоинтах: импорт не обходит лимиты.
    # Замена существующего элемента квоту не расходует.
    known_keywords = {k["keyword"] for k in await list_keyword_replies(owner_id)}
    for item in payload.keywords or []:
        keyword, reply = (
            _text(item.get("keyword"), 255),
            _text(item.get("reply_text"), 4096),
        )
        key = keyword.strip().lower() if keyword else ""
        is_new = key not in known_keywords
        if (
            key
            and reply
            and reply.strip()
            and not (is_new and len(known_keywords) >= MAX_KEYWORDS)
        ):
            await add_keyword_reply(owner_id, key, reply)
            known_keywords.add(key)
            applied += 1
        else:
            skipped += 1

    template_count = await count_templates(owner_id)

    for item in payload.templates or []:
        name, text = _text(item.get("name"), 32), _text(item.get("text"), 4096)
        key = name.strip().lower() if name else ""
        valid = bool(key) and " " not in key and bool(text and text.strip())
        if valid:
            is_new = await get_template(owner_id, key) is None
            if is_new and template_count >= MAX_TEMPLATES:
                valid = False
            elif is_new:
                template_count += 1
        if valid:
            await save_template(owner_id, key, text)
            applied += 1
        else:
            skipped += 1

    alias_count = await count_command_aliases(owner_id)
    for item in payload.aliases or []:
        alias, command = _text(item.get("alias"), 32), _text(item.get("command"), 64)
        cmd = registry.find(command.lower()) if command else None
        if (
            alias
            and alias.strip()
            and " " not in alias.strip()
            and cmd
            and registry.find(alias.strip().lower()) is None
            and await get_command_alias(owner_id, alias.strip().lower()) is None
            and alias_count < MAX_ALIASES_PER_OWNER
        ):
            await add_command_alias(owner_id, alias.strip().lower(), cmd.name)
            alias_count += 1
            applied += 1
        else:
            skipped += 1

    for chat_id in payload.favorites or []:
        await set_favorite_chat(owner_id, chat_id, True)
        applied += 1

    for item in payload.chat_flags or []:
        chat_id = item.get("chat_id")
        if isinstance(chat_id, int):
            await set_chat_flags(
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
        await upsert_reminder_settings(owner_id, **fields)
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
        await upsert_ai_settings(owner_id, **fields)
        applied += 1

    return {"applied": applied, "skipped": skipped}
