-- Warehouse DDL for Layer 2 (PostgreSQL).
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS dim_tickets_enriched (
    id                    BIGINT PRIMARY KEY,
    name                  TEXT,
    content               TEXT,
    status                INTEGER,
    type                  INTEGER,
    priority              INTEGER,
    itilcategories_id     BIGINT,
    date                  TIMESTAMP,
    date_mod              TIMESTAMP,
    solvedate             TIMESTAMP,
    closedate             TIMESTAMP,
    time_to_resolve       TIMESTAMP,
    user_requester        BIGINT,
    user_assign           BIGINT,
    entities_id           BIGINT,
    groups_id_requester   BIGINT,
    urgency               INTEGER,
    impact                INTEGER,
    is_resolved           BOOLEAN,
    is_high_priority      BOOLEAN,
    resolution_days       DOUBLE PRECISION,
    name_normalized       TEXT,
    loaded_at             TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tickets_status     ON dim_tickets_enriched(status);
CREATE INDEX IF NOT EXISTS idx_tickets_entity     ON dim_tickets_enriched(entities_id);
CREATE INDEX IF NOT EXISTS idx_tickets_category   ON dim_tickets_enriched(itilcategories_id);
CREATE INDEX IF NOT EXISTS idx_tickets_normalized ON dim_tickets_enriched(name_normalized);

CREATE TABLE IF NOT EXISTS dim_users (
    id           BIGINT PRIMARY KEY,
    name         TEXT,
    realname     TEXT,
    firstname    TEXT,
    is_active    BOOLEAN,
    entities_id  BIGINT,
    groups_id    TEXT,
    loaded_at    TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dim_entities (
    id            BIGINT PRIMARY KEY,
    name          TEXT,
    completename  TEXT,
    entities_id   BIGINT,
    level         INTEGER,
    loaded_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dim_categories (
    id                  BIGINT PRIMARY KEY,
    name                TEXT,
    completename        TEXT,
    itilcategories_id   BIGINT,
    loaded_at           TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dim_groups (
    id            BIGINT PRIMARY KEY,
    name          TEXT,
    completename  TEXT,
    groups_id     BIGINT,
    entities_id   BIGINT,
    loaded_at     TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS fact_kpis_daily (
    date                  DATE PRIMARY KEY,
    total_tickets         BIGINT NOT NULL,
    resolved_pct          DOUBLE PRECISION NOT NULL,
    high_priority_count   BIGINT NOT NULL,
    avg_resolution_days   DOUBLE PRECISION NOT NULL,
    computed_at           TIMESTAMP NOT NULL DEFAULT NOW()
);
