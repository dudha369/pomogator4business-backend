"""
Разовый перенос данных из локальной sqlite (bot.db) в Postgres (Neon).

Запуск (после того как DB_URL в .env указывает на Neon, а таблицы уже
созданы через `aerich init-db` / `aerich upgrade`):

    uv run --extra migration python -m scripts.migrate_to_postgres [путь/к/bot.db]

Если путь не передан, берётся ./bot.db (значение DB_PATH по умолчанию в
старой конфигурации). Скрипт идемпотентен НЕ является — рассчитан на разовый
прогон на пустых таблицах Postgres. Если что-то пошло не так, проще всего
пересоздать таблицы (`aerich downgrade` + `aerich upgrade` либо вручную) и
прогнать заново.
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone

import aiosqlite
from tortoise import Tortoise

from config import TORTOISE_ORM
from app.features.archive.models import ArchiveLog
from app.features.mute.models import Mute
from app.features.profile.models import ProfileBackup
from db.models import (
    ClockEmoji,
    ClockPack,
    Connection,
    DisabledModule,
    EchoChat,
    EmojiStatusSetting,
    KnownChat,
    MessageHistory,
    MessageLog,
    MirrorBot,
    StoryAutopost,
    UserLocale,
    VoiceEffect,
)

DEFAULT_DB_PATH = "bot.db"


async def _fetch_all(conn: aiosqlite.Connection, table: str):
    conn.row_factory = aiosqlite.Row
    try:
        cursor = await conn.execute(f"SELECT rowid, * FROM {table}")
    except aiosqlite.OperationalError:
        # таблицы без rowid (не должно случиться, но на всякий случай)
        cursor = await conn.execute(f"SELECT * FROM {table}")
    rows = await cursor.fetchall()
    return [dict(row) for row in rows]


async def _table_exists(conn: aiosqlite.Connection, table: str) -> bool:
    cursor = await conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    )
    return (await cursor.fetchone()) is not None


async def migrate_connections(conn):
    if not await _table_exists(conn, "connections"):
        return
    rows = await _fetch_all(conn, "connections")
    # rowid ASC => от старых к новым; расставляем created_at с шагом в 1 сек,
    # чтобы get_connection_by_owner() по-прежнему находил САМОЕ СВЕЖЕЕ
    # подключение владельца после переноса. Передаём created_at явно —
    # auto_now_add срабатывает только если поле не задано явно.
    ordered = sorted(rows, key=lambda r: r["rowid"])
    base = datetime.now(timezone.utc) - timedelta(seconds=len(ordered))
    objs = []
    for i, row in enumerate(ordered):
        objs.append(
            Connection(
                connection_id=row["connection_id"],
                owner_id=row["owner_id"],
                owner_chat_id=row["owner_chat_id"],
                owner_name=row.get("owner_name"),
                owner_username=row.get("owner_username"),
                is_enabled=bool(row["is_enabled"]),
                prefix=row["prefix"],
                rights_json=row.get("rights_json"),
                created_at=base + timedelta(seconds=i),
            )
        )
    if objs:
        await Connection.bulk_create(objs)
    print(f"connections: {len(objs)}")


async def migrate_simple(conn, table, model, mapper):
    if not await _table_exists(conn, table):
        return
    rows = await _fetch_all(conn, table)
    objs = [mapper(row) for row in rows]
    if objs:
        await model.bulk_create(objs)
    print(f"{table}: {len(objs)}")


async def _connection_owner_map(conn) -> dict:
    """connection_id -> owner_id по СТАРОЙ (sqlite) таблице connections.

    Нужно для known_chats: там раньше "известность" собеседника была
    привязана к connection_id, теперь — к owner_id (см.
    db/models/known_chat.py)."""
    if not await _table_exists(conn, "connections"):
        return {}
    rows = await _fetch_all(conn, "connections")
    return {row["connection_id"]: row["owner_id"] for row in rows}


async def migrate_known_chats(conn, connection_owner: dict):
    if not await _table_exists(conn, "known_chats"):
        return
    rows = await _fetch_all(conn, "known_chats")
    seen = set()
    objs = []
    for row in rows:
        owner_id = connection_owner.get(row["connection_id"])
        if owner_id is None:
            continue
        key = (owner_id, row["chat_id"])
        if key in seen:
            continue
        seen.add(key)
        objs.append(KnownChat(owner_id=owner_id, chat_id=row["chat_id"]))
    if objs:
        await KnownChat.bulk_create(objs)
    print(f"known_chats: {len(objs)}")


async def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_DB_PATH

    await Tortoise.init(config=TORTOISE_ORM)

    async with aiosqlite.connect(db_path) as conn:
        await migrate_connections(conn)

        await migrate_simple(
            conn,
            "disabled_modules",
            DisabledModule,
            lambda r: DisabledModule(
                connection_id=r["connection_id"], module=r["module"]
            ),
        )
        await migrate_simple(
            conn,
            "echo_chats",
            EchoChat,
            lambda r: EchoChat(connection_id=r["connection_id"], chat_id=r["chat_id"]),
        )
        await migrate_simple(
            conn,
            "message_log",
            MessageLog,
            lambda r: MessageLog(
                connection_id=r["connection_id"],
                chat_id=r["chat_id"],
                message_id=r["message_id"],
            ),
        )
        await migrate_simple(
            conn,
            "mutes",
            Mute,
            lambda r: Mute(
                connection_id=r["connection_id"],
                chat_id=r["chat_id"],
                active=bool(r["active"]),
                until=r["until"],
                warn_limit=r["warn_limit"],
                warn_count=r["warn_count"],
                warn_duration=r["warn_duration"],
            ),
        )
        await migrate_simple(
            conn,
            "story_autopost",
            StoryAutopost,
            lambda r: StoryAutopost(
                connection_id=r["connection_id"],
                enabled=bool(r["enabled"]),
                last_post_date=r["last_post_date"],
            ),
        )
        # story_queue больше не существует как фича (см. commands/story.py) —
        # её данные сознательно не переносятся.
        connection_owner = await _connection_owner_map(conn)
        await migrate_known_chats(conn, connection_owner)
        await migrate_simple(
            conn,
            "message_history",
            MessageHistory,
            lambda r: MessageHistory(
                connection_id=r["connection_id"],
                chat_id=r["chat_id"],
                message_id=r["message_id"],
                is_owner=bool(r["is_owner"]),
                text=r["text"],
                created_at=r["created_at"],
            ),
        )
        await migrate_simple(
            conn,
            "archive_log",
            ArchiveLog,
            lambda r: ArchiveLog(
                connection_id=r["connection_id"],
                chat_id=r["chat_id"],
                message_id=r["message_id"],
                event=r["event"],
                old_text=r["old_text"],
                new_text=r["new_text"],
                created_at=r["created_at"],
            ),
        )
        await migrate_simple(
            conn,
            "profile_backups",
            ProfileBackup,
            lambda r: ProfileBackup(
                connection_id=r["connection_id"],
                bio=r["bio"],
                photo_data=r["photo_data"],
                saved_at=r["saved_at"],
            ),
        )
        await migrate_simple(
            conn,
            "mirror_bots",
            MirrorBot,
            lambda r: MirrorBot(
                owner_id=r["owner_id"],
                token_encrypted=r["token_encrypted"],
                bot_id=r["bot_id"],
                bot_username=r["bot_username"],
                created_at=r["created_at"],
                is_active=bool(r["is_active"]),
            ),
        )
        await migrate_simple(
            conn,
            "clock_packs",
            ClockPack,
            lambda r: ClockPack(
                pack_index=r["pack_index"],
                pack_name=r["pack_name"],
                uploaded_count=r["uploaded_count"],
                completed=bool(r["completed"]),
            ),
        )
        await migrate_simple(
            conn,
            "clock_emojis",
            ClockEmoji,
            lambda r: ClockEmoji(
                time_key=r["time_key"],
                pack_index=r["pack_index"],
                custom_emoji_id=r["custom_emoji_id"],
            ),
        )
        await migrate_simple(
            conn,
            "emoji_status_settings",
            EmojiStatusSetting,
            lambda r: EmojiStatusSetting(
                owner_id=r["owner_id"],
                granted=bool(r["granted"]),
                enabled=bool(r["enabled"]),
            ),
        )
        await migrate_simple(
            conn,
            "user_locale",
            UserLocale,
            lambda r: UserLocale(owner_id=r["owner_id"], locale=r["locale"]),
        )
        await migrate_simple(
            conn,
            "voice_effects",
            VoiceEffect,
            lambda r: VoiceEffect(
                connection_id=r["connection_id"],
                chat_id=r["chat_id"],
                effect=r["effect"],
            ),
        )

    await Tortoise.close_connections()
    print("Готово.")


if __name__ == "__main__":
    asyncio.run(main())
