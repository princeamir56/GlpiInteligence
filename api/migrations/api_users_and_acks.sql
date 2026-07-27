-- Layer 4 — API-owned tables. Idempotent. Touches NO layer-2/3 table.
--
-- Apply against the warehouse DB (glpi_dw):
--   psql "$POSTGRES_URL" -f api/migrations/api_users_and_acks.sql
-- (strip the +psycopg2/+asyncpg driver suffix from POSTGRES_URL for psql).

CREATE TABLE IF NOT EXISTS api_users (
    id             BIGSERIAL PRIMARY KEY,
    username       TEXT NOT NULL UNIQUE,
    password_hash  TEXT NOT NULL,
    role           TEXT NOT NULL CHECK (role IN ('DSI', 'MANAGER', 'DIRECTION')),
    created_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

-- recommendations.id is TEXT (a deterministic hash), so the FK column is TEXT.
CREATE TABLE IF NOT EXISTS recommendation_acks (
    recommendation_id  TEXT   NOT NULL,
    user_id            BIGINT NOT NULL REFERENCES api_users(id) ON DELETE CASCADE,
    acknowledged_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (recommendation_id, user_id)
);

CREATE INDEX IF NOT EXISTS idx_reco_acks_user ON recommendation_acks(user_id);
