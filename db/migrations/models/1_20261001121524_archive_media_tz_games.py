from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "message_history" ADD "media_type" VARCHAR(16);
        ALTER TABLE "message_history" ADD "media_data" BYTEA;
        ALTER TABLE "ms_games" ADD "flag_mode" BOOL NOT NULL DEFAULT False;
        ALTER TABLE "ms_games" ADD "flagged" TEXT NOT NULL DEFAULT '[]';
        DROP TABLE IF EXISTS "story_queue";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        ALTER TABLE "ms_games" DROP COLUMN "flag_mode";
        ALTER TABLE "ms_games" DROP COLUMN "flagged";
        ALTER TABLE "message_history" DROP COLUMN "media_type";
        ALTER TABLE "message_history" DROP COLUMN "media_data";"""


MODELS_STATE = (
    "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"
    "yV8AUudr2YvfwfRFeIZA=="
)
