from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "alerts" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "code" VARCHAR(64) NOT NULL,
    "kind" VARCHAR(8) NOT NULL,
    "details" JSONB NOT NULL,
    "count" INT NOT NULL DEFAULT 1,
    "created_at" BIGINT NOT NULL,
    "last_at" BIGINT NOT NULL,
    "notified_at" BIGINT NOT NULL,
    "dismissed" BOOL NOT NULL DEFAULT False,
    CONSTRAINT "uid_alerts_owner_i_7191ab" UNIQUE ("owner_id", "code")
);
CREATE INDEX IF NOT EXISTS "idx_alerts_owner_i_3e43d7" ON "alerts" ("owner_id");
COMMENT ON TABLE "alerts" IS 'Активное предупреждение владельцу. Одна строка на (owner_id, code):';
        CREATE TABLE IF NOT EXISTS "alert_mutes" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "owner_id" BIGINT NOT NULL,
    "code" VARCHAR(64) NOT NULL,
    CONSTRAINT "uid_alert_mutes_owner_i_938147" UNIQUE ("owner_id", "code")
);
COMMENT ON TABLE "alert_mutes" IS '«Больше не показывать»: код полностью отключён для владельца.';"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "alert_mutes";
        DROP TABLE IF EXISTS "alerts";"""


MODELS_STATE = (
    "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"
    "WxrJk7y6F4GpEB3/8fyzbH4g=="
)
