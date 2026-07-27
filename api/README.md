# Layer 4 — API Backend (FastAPI)

Production-grade FastAPI service that reads the layer-2 warehouse (`dim_*`, `fact_*`)
and layer-3 ML result tables (`ml_*`, `recommendations`) from PostgreSQL and exposes
them as a REST API + WebSocket stream for the Angular dashboard (layer 5).

It **never writes** to the layer-2/3 tables. It owns only two small tables of its
own: `api_users` and `recommendation_acks`.

---

## 1. What it serves

| Endpoint | Purpose | Roles |
|---|---|---|
| `GET /api/overview` | Vue d'ensemble tab (KPIs, charts, top-4 alerts). Cached 60s. | all |
| `GET /api/demandeurs` | Top requesters + ML profile (`ml_user_profiles`). | all |
| `GET /api/services` | Tickets grouped by requester group with criticality. | all |
| `GET /api/sites` | Entities with counts + part%. Cached 5 min. | all |
| `GET /api/repetitifs` | Repetitive clusters (`ml_clusters`), CRITIQUE→FAIBLE. | all |
| `GET /api/techniciens` | Per-tech SLA + risk (`ml_sla_risk`). Cached 5 min. | all |
| `GET /api/categories` | Per-category volume, delays, resolution rate. | all |
| `GET /api/predictions/volume` | Next-72h daily volume forecast (`ml_forecasts`). | all |
| `GET /api/predictions/sla_risk` | SLA risk per technician (`ml_sla_risk`). | all |
| `GET /api/recommendations` | Active (non-expired) recos, filterable. | all |
| `POST /api/recommendations/{id}/acknowledge` | Mark reco seen (adds a row to `recommendation_acks`). | DSI, MANAGER |
| `WS /ws/alerts` | Real-time CRITIQUE alert stream. | any valid token |
| `POST /api/auth/login` · `/refresh` · `GET /me` | JWT auth. | — |
| `GET /health` · `/health/db` · `/metrics` | Liveness, DB readiness, Prometheus. | — |

Every data endpoint accepts optional query params: `start_date`, `end_date`,
`limit`, `entity_id`, `category_id` (documented in `/docs`).

### Roles
`DSI`, `MANAGER`, `DIRECTION`. All three can read; only `DSI`/`MANAGER` can
acknowledge. Enforced with `Depends(require_role(...))`.

---

## 2. Schema notes (important, differ from the original brief)

- **DB connection** comes from `POSTGRES_URL` (there is no Airflow `postgres_glpi`
  connection). The API auto-coerces it to the async `asyncpg` driver.
- **`recommendations.id` is `TEXT`** (a deterministic hash), so acknowledge takes a
  **string** id and `recommendation_acks.recommendation_id` is `TEXT`.
- **Recommendation type** is `AUTOMATISATION` (not `AUTOMATION`). Types:
  `FORMATION | SURCHARGE | CAUSE_RACINE | AUTOMATISATION`.
- **Severity** values are accented French: `CRITIQUE | ÉLEVÉ | MODÉRÉ | FAIBLE`.
- **`ml_forecasts` is daily** — "next 72h" = the next 3 forecast dates.
- **SLA % is computed** from `dim_tickets_enriched` (`time_to_resolve` is an SLA
  *deadline* timestamp; a ticket meets SLA when solved on/before it). It is not
  stored per technician.

---

## 3. Run it

### 3a. Local (uvicorn, dev)

```bash
cd GlpiInteligence
pip install -r api/requirements-api.txt          # isolated dep set (SQLAlchemy 2.x)

# apply the API-owned migrations against the warehouse DB (strip the driver suffix):
psql "postgresql://glpi:glpi@localhost:5432/glpi_dw" -f api/migrations/api_users_and_acks.sql
python -m api.migrations.seed_users               # creates the 3 test users

export POSTGRES_URL="postgresql+asyncpg://glpi:glpi@localhost:5432/glpi_dw"
export REDIS_URL="redis://localhost:6379/0"
export API_JWT_SECRET="$(openssl rand -hex 32)"

uvicorn api.main:app --reload --port 8000
```

### 3b. Docker Compose

A dedicated `api` service (own image `Dockerfile.api`, because it needs SQLAlchemy
2.x + asyncpg which conflict with the Airflow image's SA 1.4) is wired into
`docker-compose.yml`, exposed on **:8000**, `depends_on` postgres + redis.

```bash
docker compose up -d api
# then run the migration + seed once inside the container:
docker compose exec api sh -c \
  'python -m api.migrations.seed_users'
# (apply api/migrations/api_users_and_acks.sql via psql against glpi_dw first)
```

### 3c. Production (gunicorn)

The image default is gunicorn with 4 uvicorn workers:

```bash
gunicorn api.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

> **WebSocket + multiple workers:** the alert broadcaster keeps its client set
> in-process, so with >1 worker each worker only pushes to its own clients. Dev
> compose therefore runs a single uvicorn worker. For multi-worker prod fan-out,
> replace `AlertBroadcaster.broadcast` delivery with Redis pub/sub.

---

## 4. Seed users (DEV credentials — change in prod!)

`python -m api.migrations.seed_users` creates:

| username | password | role |
|---|---|---|
| `dsi@sartex` | `dsi-dev-password` | DSI |
| `manager@sartex` | `manager-dev-password` | MANAGER |
| `direction@sartex` | `direction-dev-password` | DIRECTION |

Passwords are bcrypt-hashed in `api_users`. **These defaults are for local testing
only.**

---

## 5. Get a token and call the API

```bash
# 1. Log in -> access + refresh tokens
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"dsi@sartex","password":"dsi-dev-password"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Call the overview endpoint with the token
curl -s http://localhost:8000/api/overview \
  -H "Authorization: Bearer $TOKEN" | python -m json.tool

# 3. With filters
curl -s "http://localhost:8000/api/sites?start_date=2026-01-01&entity_id=1&limit=20" \
  -H "Authorization: Bearer $TOKEN"

# 4. Refresh an access token
curl -s -X POST http://localhost:8000/api/auth/refresh \
  -H "Content-Type: application/json" \
  -d "{\"refresh_token\":\"<refresh>\"}"

# 5. Who am I
curl -s http://localhost:8000/api/auth/me -H "Authorization: Bearer $TOKEN"
```

### OpenAPI / Swagger UI
Interactive docs at **http://localhost:8000/docs** (ReDoc at `/redoc`). Every query
param and response model is documented there.

---

## 6. WebSocket alerts

Browsers can't set `Authorization` headers on a WebSocket, so pass the access token
as the `token` query param:

```html
<script>
  const token = "PASTE_ACCESS_TOKEN";
  const ws = new WebSocket(`ws://localhost:8000/ws/alerts?token=${token}`);
  ws.onmessage = (e) => {
    const a = JSON.parse(e.data);
    console.log(`[${a.severity}] ${a.title} — ${a.description}`);
  };
  ws.onclose = (e) => console.log("closed", e.code);  // 1008 = bad/expired token
</script>
```

A background task polls `recommendations` every `API_ALERT_POLL_SECONDS` (default 10)
for new `CRITIQUE` rows and broadcasts:

```json
{"type":"alert","severity":"CRITIQUE","title":"...","description":"...",
 "recommendation_id":"<hash>","timestamp":"2026-07-16T10:00:00+00:00"}
```

---

## 7. Health & metrics

```bash
curl http://localhost:8000/health        # {"status":"ok"}
curl http://localhost:8000/health/db     # checks Postgres; 503 if unreachable
curl http://localhost:8000/metrics       # Prometheus text (request count, latency,
                                         # default python/process metrics)
```

---

## 8. Configuration (env vars)

| var | default | meaning |
|---|---|---|
| `POSTGRES_URL` | `...glpi:glpi@postgres:5432/glpi_dw` | warehouse DB (coerced to asyncpg) |
| `REDIS_URL` | `redis://redis:6379/0` | cache |
| `API_JWT_SECRET` | `change-me-in-prod` | **override in prod** |
| `API_ACCESS_TOKEN_TTL_MIN` | `30` | access token lifetime |
| `API_REFRESH_TOKEN_TTL_DAYS` | `7` | refresh token lifetime |
| `API_ALLOWED_ORIGINS` | `http://localhost:4200` | CORS (comma-separated) |
| `API_CACHE_TTL_OVERVIEW` | `60` | overview cache TTL |
| `API_CACHE_TTL_HEAVY` | `300` | sites/techniciens cache TTL |
| `API_RATE_LIMIT_ANON` | `100/minute` | per-IP limit |
| `API_RATE_LIMIT_AUTH` | `300/minute` | per-token limit |
| `API_ALERT_POLL_SECONDS` | `10` | WS broadcaster poll interval |

All errors return a consistent envelope:
`{"error": {"code": "...", "message": "...", "details": {...}}}` — no stack traces
leak to clients. Every request carries an `X-Request-ID` (echoed in the response and
in the JSON logs).

---

## 9. Performance indexes

`api/schema_indexes.sql` adds indexes on `dim_tickets_enriched` (`date`,
`(entities_id,date)`, `(itilcategories_id,date)`, `user_assign`, `user_requester`)
and on `recommendations` — **review before applying**:

```bash
psql "postgresql://glpi:glpi@localhost:5432/glpi_dw" -f api/schema_indexes.sql
```

---

## 10. Tests

```bash
cd GlpiInteligence
python -m pytest api/tests -q
```

The DB is never hit: `get_session` is overridden and each router's query builder is
patched per-test. Auth (JWT create/verify) runs for real. Every endpoint has happy
path, auth failure, invalid params, and empty-result coverage; the WebSocket has
accept/reject + broadcaster fan-out tests. **32 tests, all green.**
