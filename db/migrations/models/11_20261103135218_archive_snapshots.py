from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "message_history" ADD "bot_id" BIGINT;
        ALTER TABLE "message_history" ADD "entities" JSONB;
        ALTER TABLE "message_history" ADD "forward" JSONB;
        ALTER TABLE "message_history" ADD "file_unique_id" VARCHAR(64);
        ALTER TABLE "message_history" ADD "file_id" VARCHAR(255);
        ALTER TABLE "message_history" ADD "file_size" BIGINT;
        ALTER TABLE "message_history" ADD "kind" VARCHAR(24);
        ALTER TABLE "message_history" ADD "show_caption_above" BOOL NOT NULL DEFAULT False;
        ALTER TABLE "message_history" ADD "payload" JSONB;
        ALTER TABLE "message_history" ADD "has_spoiler" BOOL NOT NULL DEFAULT False;
        ALTER TABLE "message_history" ADD "raw_json" JSONB;
        ALTER TABLE "archive_log" ADD "kind" VARCHAR(24);
        ALTER TABLE "archive_log" ADD "old_snapshot" JSONB;
        ALTER TABLE "archive_log" ADD "new_snapshot" JSONB;
        ALTER TABLE "archive_log" ADD "edit_kind" VARCHAR(24);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "archive_log" DROP COLUMN "kind";
        ALTER TABLE "archive_log" DROP COLUMN "old_snapshot";
        ALTER TABLE "archive_log" DROP COLUMN "new_snapshot";
        ALTER TABLE "archive_log" DROP COLUMN "edit_kind";
        ALTER TABLE "message_history" DROP COLUMN "bot_id";
        ALTER TABLE "message_history" DROP COLUMN "entities";
        ALTER TABLE "message_history" DROP COLUMN "forward";
        ALTER TABLE "message_history" DROP COLUMN "file_unique_id";
        ALTER TABLE "message_history" DROP COLUMN "file_id";
        ALTER TABLE "message_history" DROP COLUMN "file_size";
        ALTER TABLE "message_history" DROP COLUMN "kind";
        ALTER TABLE "message_history" DROP COLUMN "show_caption_above";
        ALTER TABLE "message_history" DROP COLUMN "payload";
        ALTER TABLE "message_history" DROP COLUMN "has_spoiler";
        ALTER TABLE "message_history" DROP COLUMN "raw_json";"""


MODELS_STATE = (
    "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"
)
