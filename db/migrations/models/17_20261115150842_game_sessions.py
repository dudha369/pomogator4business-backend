from tortoise import BaseDBAsyncClient

RUN_IN_TRANSACTION = True


async def upgrade(db: BaseDBAsyncClient) -> str:
    return """
        CREATE TABLE IF NOT EXISTS "game_sessions" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "game" VARCHAR(16) NOT NULL,
    "status" VARCHAR(16) NOT NULL DEFAULT 'active',
    "message_id" BIGINT,
    "state" JSONB NOT NULL,
    CONSTRAINT "uid_game_sessio_connect_6d8386" UNIQUE ("connection_id", "chat_id", "game")
);
COMMENT ON TABLE "game_sessions" IS 'Одна партия мини-игры в чате: по строке на (подключение, чат, игра).';
        DROP TABLE IF EXISTS "hangman_games";
        DROP TABLE IF EXISTS "wordle_games";
        DROP TABLE IF EXISTS "g2048_games";
        DROP TABLE IF EXISTS "city_games";
        DROP TABLE IF EXISTS "guess_games";
        DROP TABLE IF EXISTS "ms_games";
        DROP TABLE IF EXISTS "ttt_games";
        DROP TABLE IF EXISTS "chk_games";"""


async def downgrade(db: BaseDBAsyncClient) -> str:
    return """
        DROP TABLE IF EXISTS "game_sessions";
        CREATE TABLE IF NOT EXISTS "ttt_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "board" VARCHAR(16) NOT NULL,
    "turn" VARCHAR(1) NOT NULL,
    "player_x_id" BIGINT,
    "player_o_id" BIGINT,
    "status" VARCHAR(16) NOT NULL,
    "message_id" BIGINT,
    CONSTRAINT "uid_ttt_games_connect_8492c7" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "wordle_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "secret" VARCHAR(32) NOT NULL,
    "guesses" TEXT NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "message_id" BIGINT,
    "starter_id" BIGINT,
    CONSTRAINT "uid_wordle_game_connect_e68a17" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "chk_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "board" TEXT NOT NULL,
    "turn" VARCHAR(1) NOT NULL,
    "player_w_id" BIGINT,
    "player_b_id" BIGINT,
    "selected" INT,
    "status" VARCHAR(16) NOT NULL,
    "message_id" BIGINT,
    "forced_continue" boolean DEFAULT false NOT NULL,
    CONSTRAINT "uid_chk_games_connect_d75fad" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "ms_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "size" INT NOT NULL,
    "bomb_mode" VARCHAR(16) NOT NULL,
    "coop" BOOL NOT NULL,
    "mines" TEXT NOT NULL,
    "revealed" TEXT NOT NULL,
    "starter_id" BIGINT,
    "phase" VARCHAR(16) NOT NULL,
    "message_id" BIGINT,
    "flag_mode" boolean DEFAULT false NOT NULL,
    "flagged" text DEFAULT '[]'::text NOT NULL,
    CONSTRAINT "uid_ms_games_connect_f0b2f3" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "guess_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "secret" INT NOT NULL,
    "max_value" INT NOT NULL,
    "attempts" INT NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    CONSTRAINT "uid_guess_games_connect_d127e0" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "city_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "used_words" TEXT NOT NULL,
    "next_letter" VARCHAR(4),
    "status" VARCHAR(16) NOT NULL,
    CONSTRAINT "uid_city_games_connect_8e50df" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "hangman_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "secret" VARCHAR(64) NOT NULL,
    "guessed_letters" TEXT NOT NULL,
    "mistakes" INT NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "message_id" BIGINT,
    CONSTRAINT "uid_hangman_gam_connect_aae0a1" UNIQUE ("connection_id", "chat_id")
);
        CREATE TABLE IF NOT EXISTS "g2048_games" (
    "id" SERIAL NOT NULL PRIMARY KEY,
    "connection_id" VARCHAR(255) NOT NULL,
    "chat_id" BIGINT NOT NULL,
    "board" TEXT NOT NULL,
    "score" INT NOT NULL,
    "status" VARCHAR(16) NOT NULL,
    "player_id" BIGINT,
    "message_id" BIGINT,
    CONSTRAINT "uid_g2048_games_connect_1a9742" UNIQUE ("connection_id", "chat_id")
);"""


MODELS_STATE = (
    "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"
)
