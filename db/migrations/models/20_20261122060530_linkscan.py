from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "linkscan_cache" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "provider" VARCHAR(16) NOT NULL,
    "kind" VARCHAR(4) NOT NULL,
    "key" VARCHAR(64) NOT NULL,
    "level" INT NOT NULL,
    "reasons" JSONB NOT NULL,
    "expires_at" BIGINT NOT NULL,
    CONSTRAINT "uid_linkscan_ca_provide_edba0c" UNIQUE ("provider", "kind", "key")
);
CREATE INDEX IF NOT EXISTS "idx_linkscan_ca_expires_32f026" ON "linkscan_cache" ("expires_at");
COMMENT ON TABLE "linkscan_cache" IS 'Ответ одного провайдера на один адрес или хеш файла. Ключ — sha256 адреса';
        CREATE TABLE IF NOT EXISTS "linkscan_chats" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "chat_id" BIGINT NOT NULL,
    CONSTRAINT "uid_linkscan_ch_owner_i_eba84b" UNIQUE ("owner_id", "chat_id")
);
COMMENT ON TABLE "linkscan_chats" IS 'Чат, выбранный для проверки (используется при scope = \"selected\").';
        CREATE TABLE IF NOT EXISTS "linkscan_settings" (
    "owner_id" BIGINT NOT NULL PRIMARY KEY,
    "enabled" BOOL NOT NULL DEFAULT False,
    "scope" VARCHAR(8) NOT NULL DEFAULT 'all',
    "external" BOOL NOT NULL DEFAULT True
);
COMMENT ON TABLE "linkscan_settings" IS 'Настройки проверки ссылок владельца. Выключено по умолчанию: проверка в';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "linkscan_settings";
        DROP TABLE IF EXISTS "linkscan_chats";
        DROP TABLE IF EXISTS "linkscan_cache";"""


MODELS_STATE = (
    "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"
    "gargkSJfXI/T2AZV/+nsfB+uQLE3z/LzpXHjs="
)
