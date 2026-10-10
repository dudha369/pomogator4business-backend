from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "favorite_chats" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "chat_id" BIGINT NOT NULL,
    CONSTRAINT "uid_favorite_ch_owner_i_7f9c69" UNIQUE ("owner_id", "chat_id")
);
COMMENT ON TABLE "favorite_chats" IS 'Чат, который владелец пометил «избранным» (команда .fav).';
        CREATE TABLE IF NOT EXISTS "command_aliases" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "alias" VARCHAR(32) NOT NULL,
    "command" VARCHAR(64) NOT NULL,
    CONSTRAINT "uid_command_ali_owner_i_8f29ce" UNIQUE ("owner_id", "alias")
);
COMMENT ON TABLE "command_aliases" IS 'Пользовательский алиас команды: `.п` → profile. Привязан к owner_id.';
        ALTER TABLE "profile_backups" ADD "last_name" VARCHAR(255);
        ALTER TABLE "profile_backups" ADD "first_name" VARCHAR(255);
        CREATE INDEX IF NOT EXISTS "idx_archive_log_connect_75a613" ON "archive_log" ("connection_id", "event", "log_id");"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP INDEX IF EXISTS "idx_archive_log_connect_75a613";
        ALTER TABLE "profile_backups" DROP COLUMN "last_name";
        ALTER TABLE "profile_backups" DROP COLUMN "first_name";
        DROP TABLE IF EXISTS "favorite_chats";
        DROP TABLE IF EXISTS "command_aliases";"""


MODELS_STATE = (
    "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"
)
