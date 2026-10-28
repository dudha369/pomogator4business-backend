from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "quick_templates" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "name" VARCHAR(32) NOT NULL,
    "text" TEXT NOT NULL,
    CONSTRAINT "uid_quick_templ_owner_i_1814e0" UNIQUE ("owner_id", "name")
);
COMMENT ON TABLE "quick_templates" IS 'Шаблон быстрого ответа: `.t имя` подставляет текст в сообщение.';
        CREATE TABLE IF NOT EXISTS "chat_flags" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "no_autoreply" BOOL NOT NULL,
    "no_ai" BOOL NOT NULL,
    CONSTRAINT "uid_chat_flags_owner_i_7028a9" UNIQUE ("owner_id", "chat_id")
);
COMMENT ON TABLE "chat_flags" IS 'Исключения по конкретному чату: «не беспокоить» для автоответов и для ИИ.';
        CREATE TABLE IF NOT EXISTS "ai_drafts" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "source_message_id" BIGINT NOT NULL,
    "text" TEXT NOT NULL,
    "created_at" BIGINT NOT NULL,
    "status" VARCHAR(16) NOT NULL
);
COMMENT ON TABLE "ai_drafts" IS 'Черновик ответа ИИ, ожидающий решения владельца.';
        CREATE TABLE IF NOT EXISTS "ai_settings" (
    "owner_id" BIGSERIAL NOT NULL PRIMARY KEY,
    "enabled" BOOL NOT NULL,
    "mode" VARCHAR(8) NOT NULL,
    "instructions" TEXT,
    "history_messages" INT NOT NULL,
    "daily_limit" INT NOT NULL
);"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "quick_templates";
        DROP TABLE IF EXISTS "chat_flags";
        DROP TABLE IF EXISTS "ai_drafts";
        DROP TABLE IF EXISTS "ai_settings";"""


MODELS_STATE = (
    "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"
    "VwfejN7Mv/AWok9Gw="
)
