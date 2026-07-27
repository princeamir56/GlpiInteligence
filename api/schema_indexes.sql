-- Layer 4 — performance indexes on layer-2 tables for the API's aggregate queries.
-- REVIEW BEFORE APPLYING. Idempotent (IF NOT EXISTS). Adds indexes only; no data
-- or column changes to the existing warehouse tables.
--
-- Rationale: every API endpoint filters dim_tickets_enriched by a date range and
-- often by entity/category. The base schema indexes status/entity/category
-- individually but has NO index on `date` (the primary filter column) and no
-- composite covering the common (date + dimension) access pattern.

-- Primary time filter used by every endpoint's WHERE date BETWEEN ...
CREATE INDEX IF NOT EXISTS idx_tickets_date
    ON dim_tickets_enriched (date);

-- Site tab / entity_id filter combined with the date range.
CREATE INDEX IF NOT EXISTS idx_tickets_entity_date
    ON dim_tickets_enriched (entities_id, date);

-- Category tab / category_id filter combined with the date range.
CREATE INDEX IF NOT EXISTS idx_tickets_category_date
    ON dim_tickets_enriched (itilcategories_id, date);

-- Technician SLA aggregation groups by assignee.
CREATE INDEX IF NOT EXISTS idx_tickets_assign
    ON dim_tickets_enriched (user_assign);

-- Requester tab groups by requester.
CREATE INDEX IF NOT EXISTS idx_tickets_requester
    ON dim_tickets_enriched (user_requester);

-- Active (not-expired) recommendations lookup for the alerts feed.
CREATE INDEX IF NOT EXISTS idx_reco_expires
    ON recommendations (expires_at);

CREATE INDEX IF NOT EXISTS idx_reco_severity
    ON recommendations (severity);
