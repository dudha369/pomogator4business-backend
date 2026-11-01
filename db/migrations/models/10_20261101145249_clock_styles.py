"""Стили эмодзи-часов.

Aerich не умеет менять первичный ключ (поэтому в автогенерации был
ADD "time_key" и RENAME pack_index -> id, которые падали на живой БД),
SQL здесь написан вручную:
  * clock_packs / clock_emojis получают суррогатный id и колонку style;
    все существующие строки становятся стилем 'classic' (имена паков и
    custom_emoji_id не меняются);
  * emoji_status_settings.clock_style — выбранный пользователем стиль.
"""

from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "clock_packs" ADD "style" VARCHAR(32) NOT NULL DEFAULT 'classic';
        ALTER TABLE "clock_packs" DROP CONSTRAINT "clock_packs_pkey";
        ALTER TABLE "clock_packs" ADD "id" SERIAL NOT NULL PRIMARY KEY;
        ALTER TABLE "clock_emojis" ADD "style" VARCHAR(32) NOT NULL DEFAULT 'classic';
        ALTER TABLE "clock_emojis" DROP CONSTRAINT "clock_emojis_pkey";
        ALTER TABLE "clock_emojis" ADD "id" SERIAL NOT NULL PRIMARY KEY;
        ALTER TABLE "emoji_status_settings" ADD "clock_style" VARCHAR(32) NOT NULL DEFAULT 'classic';
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_clock_emoji_style_b8dc4b" ON "clock_emojis" ("style", "time_key");
        CREATE UNIQUE INDEX IF NOT EXISTS "uid_clock_packs_style_6cc300" ON "clock_packs" ("style", "pack_index");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    # возврат к одному комплекту: остаётся только classic
    return """
        DROP INDEX IF EXISTS "uid_clock_emoji_style_b8dc4b";
        DROP INDEX IF EXISTS "uid_clock_packs_style_6cc300";
        DELETE FROM "clock_packs" WHERE "style" <> 'classic';
        DELETE FROM "clock_emojis" WHERE "style" <> 'classic';
        ALTER TABLE "clock_packs" DROP COLUMN "id";
        ALTER TABLE "clock_packs" DROP COLUMN "style";
        ALTER TABLE "clock_packs" ADD PRIMARY KEY ("pack_index");
        ALTER TABLE "clock_emojis" DROP COLUMN "id";
        ALTER TABLE "clock_emojis" DROP COLUMN "style";
        ALTER TABLE "clock_emojis" ADD PRIMARY KEY ("time_key");
        ALTER TABLE "emoji_status_settings" DROP COLUMN "clock_style";"""


MODELS_STATE = (
    "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"
)
