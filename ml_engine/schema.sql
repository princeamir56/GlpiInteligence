-- Layer 3 — ML Engine result tables (PostgreSQL).
-- Idempotent: safe to re-run. Touches NONE of the layer-2 tables.

CREATE TABLE IF NOT EXISTS ml_user_profiles (
    user_id            BIGINT PRIMARY KEY,
    profile            TEXT NOT NULL,          -- autonome | standard | dependant | critique
    confidence         DOUBLE PRECISION,
    features_snapshot  JSONB,
    computed_at        TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ml_forecasts (
    category_id      BIGINT NOT NULL,
    forecast_date    DATE   NOT NULL,
    predicted_count  DOUBLE PRECISION,
    lower_bound      DOUBLE PRECISION,
    upper_bound      DOUBLE PRECISION,
    confidence       TEXT,                     -- high | low
    model_version    TEXT,
    computed_at      TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (category_id, forecast_date)
);

CREATE TABLE IF NOT EXISTS ml_sla_risk (
    technician_id        BIGINT PRIMARY KEY,
    risk_score           DOUBLE PRECISION,
    next_48h_prediction  INTEGER,
    confidence           TEXT,
    model_version        TEXT,
    computed_at          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ml_clusters (
    cluster_id     BIGINT NOT NULL,
    algorithm      TEXT   NOT NULL,            -- dbscan | kmeans
    sample_titles  JSONB,
    ticket_count   BIGINT,
    top_keywords   JSONB,
    severity       TEXT,                       -- CRITIQUE | ÉLEVÉ | MODÉRÉ | FAIBLE
    neg_ratio      DOUBLE PRECISION,
    first_seen     TIMESTAMP,
    last_seen      TIMESTAMP,
    computed_at    TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (algorithm, cluster_id)
);

CREATE TABLE IF NOT EXISTS recommendations (
    id                  TEXT PRIMARY KEY,       -- deterministic hash of type+target
    type                TEXT NOT NULL,          -- FORMATION | SURCHARGE | CAUSE_RACINE | AUTOMATISATION
    target_user_id      BIGINT,
    target_group_id     BIGINT,
    target_category_id  BIGINT,
    severity            TEXT,                   -- CRITIQUE | ÉLEVÉ | MODÉRÉ | FAIBLE
    title               TEXT NOT NULL,
    description         TEXT,
    evidence            JSONB,
    created_at          TIMESTAMP NOT NULL DEFAULT NOW(),
    expires_at          TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_reco_type       ON recommendations(type);
CREATE INDEX IF NOT EXISTS idx_reco_user       ON recommendations(target_user_id);
CREATE INDEX IF NOT EXISTS idx_forecast_date   ON ml_forecasts(forecast_date);
CREATE INDEX IF NOT EXISTS idx_clusters_sev    ON ml_clusters(severity);
