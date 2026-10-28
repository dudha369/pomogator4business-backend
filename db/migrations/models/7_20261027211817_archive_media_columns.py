from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "message_history" ADD "media_name" VARCHAR(255);
        ALTER TABLE "message_history" ADD "media_status" VARCHAR(16);
        ALTER TABLE "message_history" ADD "media_mime" VARCHAR(255);
        ALTER TABLE "archive_log" ADD "media_status" VARCHAR(16);
        ALTER TABLE "archive_log" ADD "media_mime" VARCHAR(255);
        ALTER TABLE "archive_log" ADD "media_type" VARCHAR(16);
        ALTER TABLE "archive_log" ADD "media_data" BYTEA;
        ALTER TABLE "archive_log" ADD "media_name" VARCHAR(255);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "archive_log" DROP COLUMN "media_status";
        ALTER TABLE "archive_log" DROP COLUMN "media_mime";
        ALTER TABLE "archive_log" DROP COLUMN "media_type";
        ALTER TABLE "archive_log" DROP COLUMN "media_data";
        ALTER TABLE "archive_log" DROP COLUMN "media_name";
        ALTER TABLE "message_history" DROP COLUMN "media_name";
        ALTER TABLE "message_history" DROP COLUMN "media_status";
        ALTER TABLE "message_history" DROP COLUMN "media_mime";"""


MODELS_STATE = (
    "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"
)
