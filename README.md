# GLPI Connector — Layer 1

Reliable, paginated extraction of GLPI data via the REST API. This is layer 1 of
the Sartex Group intelligent IT-support pipeline. It produces clean Python dicts
that the downstream layers (Airflow ETL, ML engine, FastAPI backend) consume.

## What it does

- Opens and closes a GLPI session (`initSession` / `killSession`) — usable as a
  context manager so the session is always released.
- Paginates `/search/{itemtype}` with `forcedisplay` (most efficient — picks
  columns up front and avoids cascading lookups for requester / assignee / etc.).
- Provides a simple `GET /{itemtype}` mode with `expand_dropdowns=true` for the
  small reference tables (User, Entity, ITILCategory, Group, ITILFollowup).
- Retries network errors and 5xx with exponential backoff (3 attempts default),
  transparently reopens expired sessions on 401, and surfaces 429 as
  `GLPIRateLimited`.
- Reads credentials only from environment variables (via `.env`).

## Install

```bash
python -m venv .venv
. .venv/Scripts/activate          # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## Configure GLPI

1. **Enable the REST API**
   In GLPI: *Setup → General → API*. Tick *Enable REST API* and copy the public
   URL. **The path differs by GLPI major version:**

   | GLPI | base URL |
   | --- | --- |
   | 9.x / 10.x | `https://glpi.company.tld/apirest.php` |
   | **11.x** | `https://glpi.company.tld/api.php/v1` |

   > **Running GLPI on the Docker host?** Containers resolve `127.0.0.1` to
   > *themselves*, so a host-local GLPI must be reached as
   > `http://host.docker.internal:8080/api.php/v1` from inside the stack. Compose
   > already defaults `GLPI_BASE_URL_CONTAINER` to that; keep the plain
   > `127.0.0.1` form in `.env` for host-side scripts.
2. **Create an API client (App-Token)**
   *Setup → General → API → Add API client*. Set the IP range that may use it,
   tick *Active*, save, and copy the generated **App-Token**.
3. **Generate a personal User-Token**
   Top-right user menu → *My settings* → tab **Remote access keys** →
   *Regenerate* next to **API token**. Copy the value.
4. **Fill in `.env`**
   ```bash
   cp .env.example .env
   # then edit .env and paste the three values
   ```

## Smoke-test the connection

```bash
python scripts/test_connection.py
```

## Populate a live GLPI with realistic demo data

The pipeline consumes GLPI in real time — it does **not** carry any static
warehouse-side fixtures. To make the dashboard light up end-to-end, seed the
GLPI instance itself via its REST API:

```bash
# uses the same GLPI_* vars from .env — no extra config
python scripts/populate_glpi.py                 # large: ~150 users, ~2500 tickets, 6 months
python scripts/populate_glpi.py --volume medium
python scripts/populate_glpi.py --volume small
python scripts/populate_glpi.py --dry-run       # preview without writing

# undo everything the script created (uses scripts/.populate_state.json)
python scripts/populate_glpi.py --wipe-created
```

The script creates 5 sites (entities), 11 department/IT groups, the full ITIL
category tree (ERP, Bureautique, Sécurité, Réseau, …), 8 technicians (incl.
Karim M. on Infrastructure Réseau as the overloaded one per the PDF), ~150
end-users spread across departments, and thousands of French tickets with
followups whose sentiment/keywords match the PDF vocabulary. Ticket creation
dates apply Monday-morning + end-of-month seasonality so the ETL's temporal
features surface the same signals the PDF describes.

Once GLPI is populated, trigger the `glpi_polling` DAG (layer 2) to pull the
data into the warehouse, then `ml_inference` (layer 3) to compute predictions
and recommendations — the Angular dashboard will populate from there.

It opens a session, iterates `/search/Ticket` to count rows, and closes the
session. Exit code `0` means everything is wired up.

## Use it from code

```python
from glpi_connector import GLPIClient, GLPIConfig, extract_tickets, extract_users

config = GLPIConfig.from_env()
with GLPIClient(config) as client:
    tickets = extract_tickets(client)
    users = extract_users(client)
```

Each extractor returns `list[dict]` with readable field names (`id`, `name`,
`status`, `priority`, …) — the GLPI search-option IDs are mapped in
`glpi_connector/extractors.py::TICKET_FIELD_MAP`.

### Verifying the Ticket field map against your instance

Search-option IDs can drift between GLPI versions and with plugins. Hit
`GET {base_url}/listSearchOptions/Ticket` and compare; override `TICKET_FIELD_MAP`
if any ID differs, e.g.:

```python
from glpi_connector.extractors import TICKET_FIELD_MAP, extract_tickets

my_map = {**TICKET_FIELD_MAP, 18: "time_to_resolve"}  # adjust IDs here
with GLPIClient(GLPIConfig.from_env()) as client:
    tickets = extract_tickets(client, field_map=my_map)
```

## Tests

```bash
pytest
```

Tests mock all HTTP calls with `requests-mock`, so they run with no network and
no live GLPI instance.

## File layout

```
glpi_connector/
├── __init__.py          public API
├── client.py            GLPIClient (auth, retries, pagination)
├── extractors.py        extract_tickets/users/entities/categories/groups/followups
├── config.py            GLPIConfig.from_env()
├── exceptions.py        GLPIAPIError + subclasses
└── tests/               pytest + requests-mock
scripts/test_connection.py
.env.example
requirements.txt
```

---

# Layer 2 — ETL & Real-Time Ingestion

Adds Airflow orchestration, Redis cache + Celery queue, pandas transformation,
and a PostgreSQL warehouse on top of layer 1.

## Stack (docker-compose)

```bash
# 1. Put your GLPI credentials in .env (same file as layer 1).
# 2. Build & start everything:
docker compose up -d
# 3. Wait ~60 s for the airflow-init job, then visit http://localhost:8080
#    (login admin / admin).
```

Services started:
- `postgres`   — both Airflow metadata DB and `glpi_dw` warehouse DB
- `redis`      — Celery broker + cache (db 0 = ETL cache, db 1 = Airflow celery)
- `airflow-webserver` / `airflow-scheduler` / `airflow-worker`
- `glpi-etl-worker` — separate Celery worker for `etl.tasks`
- `mlflow-ui` (layer 3, :5000) and `api` (layer 4, :8000)

Every service sets `restart: unless-stopped`. This matters: without it on
`postgres`/`redis`, a Docker Desktop restart brings the app containers back but
leaves the databases down, and the whole stack fails on connect while *looking*
half-healthy.

> **Port 8080 is shared.** `airflow-webserver` publishes 8080, which is also the
> usual port for a host-local GLPI. They can coexist only if GLPI binds
> `127.0.0.1` and Docker takes the wildcard — otherwise remap one of them.

## Airflow setup (one-time)

Only needed when you are **not** using docker-compose. In the Airflow UI →
**Admin → Variables**, set:

| Key | Value |
| --- | --- |
| `GLPI_BASE_URL`  | e.g. `https://glpi.company.tld/api.php/v1` (GLPI 11) |
| `GLPI_APP_TOKEN` | from GLPI |
| `GLPI_USER_TOKEN`| from GLPI |

> **Environment variables win.** `etl/config.py` reads the process environment
> first, and compose injects `GLPI_BASE_URL` / `GLPI_APP_TOKEN` /
> `GLPI_USER_TOKEN` into every Airflow container. Editing the Airflow Variable
> while running under compose therefore has **no effect** — change `.env` and
> `docker compose up -d` the affected services instead. This is a common source
> of "I updated the URL and nothing changed".

In **Admin → Connections**, create `postgres_glpi`:
- Conn Id: `postgres_glpi`
- Conn Type: `Postgres`
- Host: `postgres`, Schema: `glpi_dw`, Login: `glpi`, Password: `glpi`, Port: `5432`

The DAG `glpi_polling` is scheduled `*/10 * * * *`. Trigger it once manually to
verify, then watch `dim_tickets_enriched` fill in.

### How foreign keys are resolved (important)

`/search/Ticket` returns **display names, not ids**, for every dropdown-backed
column — `entities_id` comes back as `"Root entity > Usine A"`, not `2`. The
warehouse columns are `BIGINT`, so these cannot be inserted directly.

The pipeline therefore:

1. `transform.coerce_fk_ids` keeps the raw string in `<col>_display` and sets the
   numeric column to `NA`;
2. `load.resolve_fk_display_names` matches that string back to a real id against
   the dimension tables, indexing several spellings per row (`name`,
   `completename`, the leaf of an `A > B > C` path, and for users both
   `"realname firstname"` and `"firstname realname"`).

Two consequences to respect when editing this code:

- **Dimensions must load before tickets.** `load_postgres_task` calls
  `load_dimensions_task` first for exactly this reason. Reverse it and every FK
  silently becomes `NULL`.
- **Never "fix" a datatype mismatch with a bare `pd.to_numeric(..., errors='coerce')`
  on these columns.** It satisfies the `BIGINT` type by throwing the value away —
  the tickets load fine and every category/site/user link is quietly `NULL`.

A ticket with no category in GLPI legitimately keeps `itilcategories_id = NULL`;
the API renders those as *Sans catégorie*. Sanity-check the fill rate with:

```bash
docker compose exec postgres psql -U glpi -d glpi_dw -c \
  "SELECT count(*) total, count(itilcategories_id) cat, count(entities_id) ent
     FROM dim_tickets_enriched;"
```

## Verifying

```bash
docker compose exec postgres psql -U glpi -d glpi_dw -c \
  "SELECT count(*) FROM dim_tickets_enriched;"
docker compose exec postgres psql -U glpi -d glpi_dw -c \
  "SELECT * FROM fact_kpis_daily ORDER BY date DESC LIMIT 5;"
```

## Layer-2 layout

```
etl/
├── config.py        Airflow Variables -> GLPIConfig + ETLConfig (PG/Redis URLs)
├── cache.py         Redis wrapper, two TTL tiers (5 min live, 1 h aggregate)
├── tasks.py         Celery app + transform/load tasks
├── transform.py     TicketTransformer (pure pandas — testable in isolation)
├── load.py          SQLAlchemy upserts via staging tables
├── schema.sql       Warehouse DDL
├── dags/glpi_polling_dag.py   TaskFlow DAG, runs every 10 min
└── tests/           pytest (transform, cache w/ fakeredis, load w/ sqlite)
```

## Running layer-2 tests

```bash
pip install -r requirements.txt
pytest etl/tests
```

---

# Layer 3 — ML Engine (predictions & recommendations)

The intelligence layer. It reads the clean warehouse tables written by layer 2
(`dim_tickets_enriched`, `dim_*`), trains/applies four model families, and writes
predictions & recommendations back into new `ml_*` + `recommendations` tables that
layer 4 (FastAPI) reads. Nothing in layer 1/2 was modified.

> A dedicated, deeper guide lives in [`ml_engine/README.md`](ml_engine/README.md).
> This section is the quick "how to set up & run" for the whole stack.

## What it does — four modules

| Module | Problem | Algorithm |
| --- | --- | --- |
| `ml_engine/models/classifier.py` | Profile requesters into `autonome` / `standard` / `dependant` / `critique` | RandomForest over rule-bootstrapped labels |
| `ml_engine/models/forecaster.py` | 72 h ticket-volume forecast per top-N category | Prophet (avg fallback on short series) |
| `ml_engine/models/sla_risk.py`   | 48 h SLA-violation risk per technician | XGBoost (rate fallback) |
| `ml_engine/models/clusterer.py`  | Group French tickets, surface recurring root causes | spaCy + sentence-transformers + DBSCAN/K-Means + sentiment |
| `ml_engine/recommender.py`       | Actionable DSI recommendations | rule engine (`ml_engine/rules.yaml`) |

Results land in `ml_user_profiles`, `ml_forecasts`, `ml_sla_risk`, `ml_clusters`
and `recommendations` (DDL in `ml_engine/schema.sql`).

## Design decisions (as agreed)

- **Embeddings**: `sentence-transformers` `paraphrase-multilingual-MiniLM-L12-v2`
  (French-capable, ~470 MB, CPU-friendly) rather than CamemBERT. Weights are baked
  into the Airflow image so inference never re-downloads them.
- **MLflow**: **SQLite-backed** tracking. A DB backend is **required** for the
  model registry / Production stage — a plain `file:./mlruns` store cannot
  register models. MLflow is pinned `>=2.12,<3` because 3.x needs SQLAlchemy 2.0,
  which conflicts with Airflow 2.9.3 (SQLAlchemy 1.4). Paths differ by context:

  | | tracking URI | artifacts |
  | --- | --- | --- |
  | local | `sqlite:///mlflow.db` | `./mlartifacts` |
  | **compose** | `sqlite:////opt/airflow/mlruns/mlflow.db` | `/opt/airflow/mlruns/artifacts` |

  In compose both live on the shared `mlruns` volume so every worker and the
  MLflow UI see the same registry. **That volume must be writable by uid 50000**
  (the `airflow` user). `Dockerfile.airflow` creates `/opt/airflow/mlruns` in the
  image so a fresh named volume inherits airflow ownership — if the directory
  were absent, Docker would create it `root`-owned and *every* ML task would die
  with `sqlite3.OperationalError: unable to open database file`. To repair an
  already-root-owned volume:

  ```bash
  docker run --rm --user 0:0 -v glpiinteligence_mlruns:/mnt alpine \
    sh -c "mkdir -p /mnt/artifacts && chown -R 50000:0 /mnt"
  ```
- **Cold start**: below `ML_COLD_START_MIN_ROWS` (default 100) rows the classifier
  and SLA model skip training and warn; the forecaster falls back to trailing
  averages flagged `confidence: low`.
- **Zero-Airflow modules**: `features.py` and every `models/*.py` have no Airflow
  imports; the DAG tasks are thin wrappers. All heavy deps are imported lazily so
  the light modules (and most tests) run without them.
- **Follow-up text**: layer 2 does not persist `TicketFollowup.content`, so NLP runs
  on `name` + `content`. `features.build_text_corpus` has a hook to fold followups
  in once a `dim_followups` table exists.

## Setup

The ML deps are already in `requirements.txt`. For a **local** (non-Docker) run:

```bash
pip install -r requirements.txt
python -m spacy download fr_core_news_sm    # French lemmatizer for the NLP module
cp .env.example .env                        # then set MLFLOW_* / POSTGRES_URL if outside compose
```

For the **Docker** stack, the ML deps + CPU `torch` + `fr_core_news_sm` + the
pre-cached embedding model are all baked into `Dockerfile.airflow` — just rebuild:

```bash
docker compose build
docker compose up -d
```

Postgres access reuses layer 2's `POSTGRES_URL` (the `glpi_dw` warehouse) — no new
credentials. In compose, `MLFLOW_TRACKING_URI` / `MLFLOW_ARTIFACT_ROOT` point at a
shared `mlruns` volume so every worker and the MLflow UI see the same registry.

## 1. Create the ML tables (does not touch layer-2 tables)

```bash
# local
python -m ml_engine.migrate
# or inside the stack
docker compose exec airflow-worker python -m ml_engine.migrate
```

## 2. Train & register the first models

```bash
# trains on the warehouse, prints metrics; --register logs + registers in MLflow
python -m ml_engine.models.classifier --train --register
```

The **retrain DAG** `ml_retrain` (weekly, Sunday 02:00) trains all four models,
evaluates them, registers new versions, and promotes to **Production** only when
the primary metric improves. Inference always loads the latest Production model
from the registry — never a hardcoded pickle path.

## 3. Run inference

The **inference DAG** `ml_inference` runs hourly:

```
check_data_freshness
      └─► classify_users
      └─► forecast_volume + predict_sla_risk
      └─► cluster_tickets
                 └─► generate_recommendations ─► load_ml_results
```

Trigger it once manually from the Airflow UI (http://localhost:8080) to verify.
Both `ml_inference` and `ml_retrain` appear there automatically — their DAG files
are mounted under `dags/ml_engine/`.

> **The four model tasks run one at a time** (`max_active_tasks=1`), and Celery
> worker concurrency is capped at 2 (`AIRFLOW__CELERY__WORKER_CONCURRENCY`).
> Celery otherwise defaults to one process per CPU, which lets a dozen
> memory-hungry tasks (Prophet, sentence-transformers, spaCy, XGBoost) start
> simultaneously and get OOM-killed on a small Docker VM. Serialising them also
> avoids concurrent Alembic migrations racing on the single SQLite tracking file
> the first time MLflow initialises — a failure that shows up as a task exiting
> with code 1 and **no Python traceback**.

On a fresh volume the first MLflow call runs the full Alembic migration chain.
Do it once, serially, before the first DAG run:

```bash
docker compose exec airflow-worker python -c \
  "import mlflow,os; mlflow.set_tracking_uri(os.environ['MLFLOW_TRACKING_URI']); \
   from mlflow.tracking import MlflowClient; MlflowClient().search_experiments()"
```

## 4. Verify predictions landed in Postgres

```bash
docker compose exec postgres psql -U glpi -d glpi_dw -c \
  "SELECT profile, count(*) FROM ml_user_profiles GROUP BY profile;"
docker compose exec postgres psql -U glpi -d glpi_dw -c \
  "SELECT type, severity, title FROM recommendations ORDER BY created_at DESC LIMIT 10;"
```
Other tables: `ml_forecasts`, `ml_sla_risk`, `ml_clusters`.

## 5. Open the MLflow UI

With the stack up, the `mlflow-ui` service exposes it on **http://localhost:5000**.
Locally:

```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db --default-artifact-root ./mlartifacts
```

## 6. Tune recommendations

Edit `ml_engine/rules.yaml` (training concentration %, surcharge volume multiplier
& SLA threshold, root-cause min tickets, repetitive count) and re-run `ml_inference`.
No code change needed.

## Layer-3 layout

```
ml_engine/
├── config.py            MLConfig.from_env() (POSTGRES_URL, MLFLOW_*, cold-start)
├── features.py          per-model feature engineering — pure pandas
├── data_access.py       read dim_tickets_enriched / freshness check
├── models/
│   ├── classifier.py    user profiles (RandomForest) + CLI
│   ├── forecaster.py    Prophet volume forecast
│   ├── sla_risk.py      XGBoost SLA risk
│   └── clusterer.py     NLP preprocessing + embeddings + DBSCAN/K-Means
├── recommender.py       rule engine (loads rules.yaml)
├── rules.yaml           human-editable recommendation thresholds
├── registry.py          MLflow helpers (log_run / promote / load_production_model)
├── load.py              upsert into ml_* tables + recommendations
├── schema.sql           DDL for the new tables
├── migrate.py           creates the ml_* tables (idempotent)
├── dags/
│   ├── ml_inference_dag.py   hourly inference
│   └── ml_retrain_dag.py     weekly retrain + conditional promotion
└── tests/               pytest with small synthetic DataFrames (no PG/GPU)
```

## Running layer-3 tests

```bash
pip install -r requirements.txt
pytest ml_engine/tests
```

All tests use small synthetic DataFrames — no live Postgres or GPU. Model paths
that need heavy deps fall back gracefully (or the model is downloaded on first run).

---

# Layer 4 — API Backend (FastAPI)

The serving layer. A production-grade **async FastAPI** service that reads the
layer-2 warehouse (`dim_*`, `fact_*`) and layer-3 ML tables (`ml_*`,
`recommendations`) and exposes them as a **REST API + WebSocket stream** for the
Angular dashboard (layer 5). It **never writes** to the layer-2/3 tables — it owns
only two small tables of its own: `api_users` and `recommendation_acks`.

> A dedicated, deeper guide (every endpoint, curl recipes, the JS WebSocket
> snippet, full env-var table) lives in [`api/README.md`](api/README.md). This
> section is the quick "how to config & run".

## What it serves

- `GET /api/overview` — Vue d'ensemble tab (6 KPI cards, 4 charts, top-4 alerts). Cached 60 s.
- Per-tab: `GET /api/demandeurs`, `/services`, `/sites`, `/repetitifs`,
  `/techniciens`, `/categories`. `sites` + `techniciens` cached 5 min.
- Predictions: `GET /api/predictions/volume` (next 72 h = next 3 daily forecasts),
  `GET /api/predictions/sla_risk`.
- Recommendations: `GET /api/recommendations` (filterable by `type`/`severity`),
  `POST /api/recommendations/{id}/acknowledge`.
- Real-time: `WS /ws/alerts` — pushes new `CRITIQUE` recommendations as they appear.
- Auth: `POST /api/auth/login` · `/refresh` · `GET /api/auth/me` (JWT, roles
  `DSI` / `MANAGER` / `DIRECTION`; all read, only DSI/MANAGER may acknowledge).
- Ops: `GET /health`, `GET /health/db`, `GET /metrics` (Prometheus).

Every data endpoint accepts optional `start_date`, `end_date`, `limit`,
`entity_id`, `category_id` — all documented in the OpenAPI UI.

## Why the API has its own image & dep set

The API needs **SQLAlchemy 2.x + asyncpg**, which conflicts with the Airflow image's
pinned SQLAlchemy 1.4 (Airflow 2.9.3). So Layer 4 does **not** reuse the
`glpi-airflow` image: it has its own `Dockerfile.api` (python:3.11-slim) and its own
isolated dependency file [`api/requirements-api.txt`](api/requirements-api.txt). The
compose service is named `api`, exposed on **:8000**, `depends_on` postgres + redis.

## Configure

Reuses `POSTGRES_URL` + `REDIS_URL` from layers 2/3 (the API auto-coerces the
Postgres URL to the async `asyncpg` driver). API-specific vars live in the same
`.env` (see the block added to `.env.example`):

| var | default | meaning |
| --- | --- | --- |
| `API_JWT_SECRET` | `change-me-in-prod` | JWT signing secret — **override in prod** |
| `API_ACCESS_TOKEN_TTL_MIN` | `30` | access-token lifetime |
| `API_REFRESH_TOKEN_TTL_DAYS` | `7` | refresh-token lifetime |
| `API_ALLOWED_ORIGINS` | `http://localhost:4200` | CORS origins (comma-separated) |
| `API_CACHE_TTL_OVERVIEW` | `60` | overview cache TTL (s) |
| `API_CACHE_TTL_HEAVY` | `300` | sites/techniciens cache TTL (s) |
| `API_RATE_LIMIT_ANON` / `_AUTH` | `100/minute` / `300/minute` | rate limits (per IP / per token) |
| `API_ALERT_POLL_SECONDS` | `10` | WS broadcaster poll interval |

## 1. Create the API tables + seed test users

```bash
# api_users + recommendation_acks (idempotent; touches no layer-2/3 table).
# psql needs the plain URL — strip the +asyncpg/+psycopg2 driver suffix:
psql "postgresql://glpi:glpi@localhost:5432/glpi_dw" -f api/migrations/api_users_and_acks.sql

# one bcrypt-hashed user per role (DEV passwords — see table below):
python -m api.migrations.seed_users
```

Seed users (**DEV credentials — change in prod**):

| username | password | role |
| --- | --- | --- |
| `dsi@sartex` | `dsi-dev-password` | DSI |
| `manager@sartex` | `manager-dev-password` | MANAGER |
| `direction@sartex` | `direction-dev-password` | DIRECTION |

Optionally apply the perf indexes (**review first**):
`psql "postgresql://glpi:glpi@localhost:5432/glpi_dw" -f api/schema_indexes.sql`.

## 2. Run it

### Local (uvicorn, dev)

```bash
pip install -r api/requirements-api.txt      # isolated dep set (SQLAlchemy 2.x)
export POSTGRES_URL="postgresql+asyncpg://glpi:glpi@localhost:5432/glpi_dw"
export REDIS_URL="redis://localhost:6379/0"
export API_JWT_SECRET="$(openssl rand -hex 32)"
uvicorn api.main:app --reload --port 8000
```

### Docker Compose

```bash
docker compose up -d api            # builds Dockerfile.api, starts on :8000
# then run step 1 (migration + seed) once against glpi_dw
```

### Production (gunicorn)

The image default is gunicorn with 4 uvicorn workers:

```bash
gunicorn api.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

> **WebSocket + workers:** the alert broadcaster holds its client set in-process, so
> with >1 worker each only serves its own clients. Dev compose therefore runs a
> single uvicorn worker; for multi-worker prod fan-out, swap the broadcaster's
> delivery for Redis pub/sub (noted in `api/alerts/broadcaster.py`).

## 3. Get a token and call the API

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"dsi@sartex","password":"dsi-dev-password"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

curl -s http://localhost:8000/api/overview -H "Authorization: Bearer $TOKEN" | python -m json.tool
curl -s "http://localhost:8000/api/sites?start_date=2026-01-01&limit=20" -H "Authorization: Bearer $TOKEN"
```

- **Swagger UI**: http://localhost:8000/docs (ReDoc at `/redoc`).
- **WebSocket** (token as query param — browsers can't set WS headers):
  ```js
  const ws = new WebSocket(`ws://localhost:8000/ws/alerts?token=${TOKEN}`);
  ws.onmessage = (e) => console.log(JSON.parse(e.data));  // {type:"alert", severity:"CRITIQUE", ...}
  ```
- **Ops**: `curl http://localhost:8000/health` · `/health/db` · `/metrics`.

All errors return a consistent envelope `{"error":{"code","message","details"}}` (no
stack traces leak); every response carries an `X-Request-ID` echoed in the JSON logs.

## Layer-4 layout

```
api/
├── main.py              app factory: CORS, rate limit, JSON logging, error envelope, routers, /metrics
├── config.py            pydantic-settings; coerces POSTGRES_URL -> asyncpg
├── database.py          async engine + get_session dependency
├── security.py          JWT create/verify, bcrypt, require_role(...) deps
├── cache.py             async Redis wrapper (overview 60s / heavy 5min tiers)
├── logging_config.py    JSON logs with request_id/user/route/duration
├── routers/             one module per tab + auth, predictions, recommendations, websocket, health
├── schemas/             Pydantic v2 request/response models (common, auth, overview, tabs)
├── queries/             SQL builders (shared WHERE, overview, tabs, predictions, recommendations)
├── alerts/broadcaster.py   background poller -> WebSocket fan-out
├── migrations/          api_users_and_acks.sql + seed_users.py
├── schema_indexes.sql   perf indexes on dim_tickets_enriched (review before applying)
├── requirements-api.txt isolated deps (SQLAlchemy 2.x + asyncpg)
└── tests/               42 pytest tests (DB mocked, JWT real)
Dockerfile.api           dedicated image (python:3.11-slim)
```

## Running layer-4 tests

```bash
pip install -r api/requirements-api.txt
python -m pytest api/tests -q          # 42 passed
```

The DB is never hit: `get_session` is overridden and each router's query builder is
patched per-test; JWT create/verify runs for real. Every endpoint has happy-path,
auth-failure, invalid-param and empty-result coverage, plus WebSocket accept/reject
and broadcaster fan-out tests.

---

# Layer 5 — Angular Dashboard (frontend)

The presentation layer. A premium-feeling **Angular 17 standalone** SPA that consumes
the layer-4 REST API + WebSocket and renders the Vue d'ensemble and per-tab analytics
as an interactive, themeable dashboard. It **only reads** the API — it holds no
database of its own and never talks to layers 1–3 directly.

Lives in [`frontend/`](frontend/), sibling to `api/`, `etl/`, `ml_engine/`,
`glpi_connector/`. Built with the Angular CLI — nothing in the Python layers was
touched.

## Stack & key decisions

- **Angular 17+, standalone components** (no NgModules), lazy-loaded routes, **Angular
  signals + RxJS** for state (no NgRx store).
- **Charts**: `chart.js` + `ng2-charts@5` (the Angular-17-compatible line; v6+ needs
  Angular 21). Chart.js registerables are registered once in `app.config.ts`.
- **Icons**: `lucide-angular`. **Fonts**: Inter + JetBrains Mono via `@fontsource/*`
  (bundled locally, no Google CDN). **Alerts/toasts**: `sweetalert2`, wrapped in a
  `NotificationService`.
- **Two first-class themes** (light + dark). The whole palette — the Sartex brand
  indigo `#27316E` and its scale, semantics, warm neutrals — lives as CSS custom
  properties in `src/styles.css`; components never hardcode colors. Charts re-read the
  variables and redraw on theme toggle.
- **Auth**: JWT stored in `localStorage`, attached by a `jwt` HTTP interceptor; a
  `refresh` interceptor auto-renews on 401; an `error` interceptor surfaces failures as
  toasts. `authGuard` protects everything except `/login`.

## Prerequisites

- **Node ≥ 18** and npm (built and tested on Node 22 / npm 10).
- A **running layer-4 API on `http://localhost:8000`** (see Layer 4 above), reachable
  with the seed users. The dashboard is useless without it — the login call and every
  tab hit that API.
- The API must allow the dashboard origin in CORS: keep
  `API_ALLOWED_ORIGINS=http://localhost:4200` (the default) in `.env`.

## 1. Install

```bash
cd frontend
npm install
```

## 2. Configure the backend URL

The API base + WebSocket URLs come from `src/environments/environment.ts`:

```ts
export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  wsBaseUrl: 'ws://localhost:8000',
};
```

Change these two values if your API runs elsewhere (e.g. a LAN host or a different
port). `environment.prod.ts` holds the production equivalents. No other config is
needed — everything else (theme, sidebar state, JWT) is persisted client-side in
`localStorage`.

## 3. Run it (dev)

```bash
npm start           # = ng serve, opens http://localhost:4200
```

Then log in with a **layer-4 seed user** (the API must be up):

| username | password | role |
| --- | --- | --- |
| `dsi@sartex` | `dsi-dev-password` | DSI |
| `manager@sartex` | `manager-dev-password` | MANAGER |
| `direction@sartex` | `direction-dev-password` | DIRECTION |

After login you land on **Vue d'ensemble** (`/dashboard`). If the API is down or a
response shape doesn't match, tabs show a styled error/empty state rather than
crashing.

## 4. Using the dashboard

- **Theme toggle** — the animated switch in the header flips light ⇄ dark; the choice
  persists across reloads. Explicit light / dark / auto (follow OS) also live in
  **Paramètres** (`/settings`).
- **Sidebar** — collapsible (state persisted); the 7 analytics tabs plus Settings and
  Logout.
- **Real-time alerts** — `CRITIQUE` recommendations pushed over `WS /ws/alerts` appear
  as top-right toasts and increment the header bell's unread badge.
- **Tables** — every tab table is sortable, searchable, paginated, and **exports to
  CSV** from its toolbar.

## 5. Build for production

```bash
npm run build       # outputs to frontend/dist/frontend/
```

Serve `dist/frontend/browser/` behind any static host (nginx, Caddy, `http-server`).
Make sure `apiBaseUrl` in `environment.prod.ts` points at the reachable API and that
the API's `API_ALLOWED_ORIGINS` includes the dashboard's deployed origin.

## 6. Tests & lint

```bash
npm test            # Karma + Jasmine unit specs (one per component)
ng lint             # if @angular-eslint is configured
```

## Layer-5 layout

```
frontend/src/app/
├── core/
│   ├── services/      api, auth, dashboard, websocket, theme, notification
│   ├── interceptors/  jwt, refresh, error
│   ├── guards/        auth, role
│   └── models/        TS interfaces mirroring the API responses
├── shared/
│   ├── components/    kpi-card, data-table, bar/horiz-bar/donut/scatter-chart,
│   │                  sla-bar, badge, skeleton-loader, theme-toggle, alerts-panel
│   ├── directives/    count-up (animated numbers), stagger (list mount)
│   └── animations.ts  route fade/slide, fade-up, stagger triggers
├── layout/            main-layout (sidebar + header + outlet), sidebar, header, auth-layout
├── pages/             dashboard (Vue d'ensemble), demandeurs, services, sites,
│                      repetitifs, techniciens, categories, login, settings
├── app.config.ts      providers: router, HttpClient + interceptors, animations, icons, Chart.js
└── app.routes.ts      lazy-loaded routes behind authGuard
```

> **Response shapes**: the TypeScript models under `core/models/` mirror the layer-4
> Pydantic schemas. If you change an API response, update the matching model (and any
> mapping in the tab component) so the tab reads the new fields.

---

# Operations & Troubleshooting

Failure modes seen on this stack, with the diagnosis that actually identifies
each one. Work top-down: most "the dashboard is wrong" reports are the first two.

## Diagnostic order

```bash
docker compose ps                        # all 9 up? postgres/redis healthy?
docker compose exec -T postgres psql -U glpi -d glpi_dw -c \
  "SELECT count(*) total, count(itilcategories_id) cat FROM dim_tickets_enriched;"
docker compose exec -T postgres psql -U airflow -d airflow -c \
  "SELECT dag_id, run_id, state FROM dag_run ORDER BY start_date DESC LIMIT 5;"
```

Airflow's CLI is slow and hangs when the scheduler is busy; querying the metadata
DB directly (as above) is faster and more reliable for run/task state.

## The dashboard shows a stale or wrong ticket count

The warehouse is authoritative — check it before touching the API:

```bash
docker compose exec -T postgres psql -U glpi -d glpi_dw -c \
  "SELECT count(*) FROM dim_tickets_enriched;"
```

- **Warehouse also low** → the ETL is the problem. Note GLPI caps `/search` page
  size (`list_limit_max`, often 500) and trims the last page; `client.search`
  advances by `len(data)`, never by the requested `size`, or pagination silently
  stops early.
- **Warehouse correct, API stale** → the overview response is cached 60 s:
  `docker compose exec redis redis-cli -n 0 FLUSHDB`.

## A tab shows "Impossible de charger les données" / `0 Unknown Error`

Status `0` means the browser never got a readable response — it is **not** an API
error code. Reproduce server-side to get the real status:

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"dsi@sartex","password":"dsi-dev-password"}' \
  | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8000/api/categories \
  -H "Authorization: Bearer $TOKEN"
docker compose logs --tail 200 api | grep "unhandled error"
```

`CORSMiddleware` is registered **last** in `api/main.py` so it is the outermost
layer. Starlette wraps middleware in reverse registration order — register CORS
before the error-handling `context_middleware` and the 500 it synthesises escapes
without an `Access-Control-Allow-Origin` header, so the browser blocks it and the
UI can only report an opaque `0`. Keep CORS last.

### Two SQL traps behind those 500s

- **`'x #'||NULL` is `NULL` in SQL.** A label built by concatenating a nullable id
  yields `NULL`, not the prefix, and fails a non-optional Pydantic `str`. Always
  end the `COALESCE` with a literal (`'Sans catégorie'`, `'Sans site'`, `'Inconnu'`).
- **A `LEFT JOIN` fallback must use the fact-side column.** `COALESCE(..., u.id)`
  is `NULL` on a join miss; use the ticket-side id (`t.user_assign`) — see
  `queries/shared.py::user_name_expr`.

**asyncpg is strict about parameter types**: it infers `$1` in
`(:horizon || ' days')::interval` as text and rejects an int bind. Use
`make_interval(days => :horizon)`. Likewise it refuses a tz-aware datetime bound
against a naive `TIMESTAMP` column.

## An Airflow task fails

Read the task log before re-triggering — retriggering a task that fails
deterministically just burns minutes:

```bash
docker compose exec airflow-scheduler bash -lc \
  "tail -n 40 '/opt/airflow/logs/dag_id=<dag>/run_id=<run_id>/task_id=<task>/attempt=1.log'"
```

- **`column "is_active" is of type boolean but expression is of type bigint`** —
  pandas infers the staging table's types, and GLPI returns `0/1` for booleans.
  Dimension columns are cast explicitly in `load.DIM_COLUMN_CASTS`; extend it
  when adding a column rather than casting in SQL.
- **`'DateTime' object is not subscriptable`** — Airflow injects `execution_date`
  as a pendulum `DateTime`, not a string. Normalise it (`_to_day_iso`) instead of
  slicing.
- **Exit code 1 with no traceback** — the process was killed (OOM) or died in a
  native/migration step. Check `docker stats` and the VM's own memory
  (`docker run --rm alpine free -m`); if swap is near-full, reduce concurrency
  rather than raising limits.
- **Task stuck `queued` > 5 min** — check the DAG is unpaused, `max_active_runs`
  /`max_active_tasks` aren't already saturated by an orphaned `running` run, and
  that a worker is actually alive.
- **Orphaned `running` run** (left by a Docker restart) blocks the next run under
  `max_active_runs=1`; clear it:
  ```bash
  docker compose exec -T postgres psql -U airflow -d airflow -c \
    "UPDATE dag_run SET state='failed', end_date=NOW()
       WHERE dag_id='glpi_polling' AND state='running';"
  ```

## Docker Desktop hangs or returns HTTP 500

On a memory-constrained host the engine itself becomes unresponsive — `docker ps`
hangs and the API returns
`request returned 500 Internal Server Error ... /containers/json`. This is the
host, not the pipeline. Recover with `docker desktop restart`, then confirm
`postgres`/`redis` came back up.

**Sizing:** the full stack (9 containers, Airflow + 2 Celery workers + Postgres +
the ML libraries) wants **~6 GB** for Docker, and Docker's allocation should stay
**well under total host RAM** — allocating 6 GB on an 8 GB machine starves
Windows and makes the engine *less* stable, not more. On a small host, prefer:

```bash
docker compose stop mlflow-ui airflow-webserver   # optional; frees ~500 MB
```

Both are convenience UIs — DAGs run fine without them (trigger via
`docker compose exec airflow-scheduler airflow dags trigger <dag>`).

## PowerShell notes (Windows)

`docker compose exec -T <svc> python -c "..."` mangles quoting badly. Pipe a
file instead:

```powershell
Get-Content script.py -Raw | docker compose exec -T airflow-worker python -
```

Accented output (`Réseau` → `RÃ©seau`) in the PowerShell console is a terminal
encoding artefact, not corrupted data — verify with `psql` before "fixing" it.

