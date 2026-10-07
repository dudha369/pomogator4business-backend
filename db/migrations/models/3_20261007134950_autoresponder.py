from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "autoresponder_settings" (
    "owner_id" BIGINT NOT NULL PRIMARY KEY,
    "greeting_enabled" BOOL NOT NULL,
    "greeting_text" TEXT,
    "away_enabled" BOOL NOT NULL,
    "away_text" TEXT,
    "away_start_minutes" INT,
    "away_end_minutes" INT,
    "auto_read_enabled" BOOL NOT NULL
);
        CREATE TABLE IF NOT EXISTS "keyword_replies" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "keyword" VARCHAR(255) NOT NULL,
    "reply_text" TEXT NOT NULL,
    CONSTRAINT "uid_keyword_rep_owner_i_32f668" UNIQUE ("owner_id", "keyword")
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "keyword_replies";
        DROP TABLE IF EXISTS "autoresponder_settings";"""


MODELS_STATE = (
    "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"
    "+sl8HAcX269PhV+AUuDr2Yffk/tPwGZA=="
)
