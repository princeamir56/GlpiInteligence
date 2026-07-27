# Layer 3 — ML Engine

Prediction & recommendation layer. Reads the clean warehouse tables written by
layer 2 (`dim_tickets_enriched`, `dim_*`), trains/applies four model families,
and writes results into new `ml_*` + `recommendations` tables that layer 4
(FastAPI) reads.

## Modules

| File | Problem | Algorithm |
|------|---------|-----------|
| `models/classifier.py` | 3.1 User profiling (`autonome`/`standard`/`dependant`/`critique`) | RandomForest over rule-bootstrapped labels |
| `models/forecaster.py` | 3.2a 72h volume forecast per top-N category | Prophet (avg fallback on short series) |
| `models/sla_risk.py`   | 3.2b 48h SLA-violation risk per technician | XGBoost (rate fallback) |
| `models/clusterer.py`  | 3.3 French NLP root-cause clustering | spaCy + sentence-transformers + DBSCAN/KMeans |
| `recommender.py`       | 3.4 Rule engine over 3.1–3.3 | `rules.yaml` |

### Design guarantees
- `features.py` and every `models/*.py` have **zero Airflow imports** and expose the
  uniform interface `train(df) -> model`, `predict(model, df) -> DataFrame`,
  `evaluate(model, df) -> dict[str, float]`. The retrain DAG loops over all four.
- Heavy deps (prophet, mlflow, spaCy, sentence-transformers, torch) are imported
  **lazily** inside functions — the light modules import fast and the test suite
  runs without them (those paths degrade to average/TF-IDF fallbacks).
- `random_state=42` everywhere it's supported; the input DataFrame hash is logged
  to MLflow for reproducibility.
- **Cold start**: below `ML_COLD_START_MIN_ROWS` (default 100) rows, the classifier
  and SLA model skip training and emit a warning instead of crashing; the
  forecaster falls back to trailing averages with `confidence="low"`.

## Design choices (as agreed)
- **Embeddings**: `sentence-transformers` `paraphrase-multilingual-MiniLM-L12-v2`
  (French-capable, ~470 MB, CPU-friendly) over CamemBERT for a lighter footprint.
  Weights cache under `ML_MODEL_CACHE_DIR` after first download.
- **MLflow**: SQLite-backed tracking (`sqlite:///mlflow.db`) with artifacts under
  `./mlartifacts`. A DB backend is **required** for the model registry / Production
  stage — a plain `file:./mlruns` store cannot register models. SQLite needs no
  extra service; swap `MLFLOW_TRACKING_URI` for a server URL to share a registry.
- **Follow-up text**: layer 2 does not persist `TicketFollowup.content`, so 3.3
  runs on `name` + `content`. `features.build_text_corpus` has a documented hook
  to fold in followups once a `dim_followups` table exists.

## Setup

```bash
pip install -r requirements.txt
python -m spacy download fr_core_news_sm     # French lemmatizer for 3.3
cp .env.example .env                          # then edit if running outside compose
```

Postgres access reuses layer 2's `POSTGRES_URL` (the `glpi_dw` warehouse) — no new
credentials.

## 1. Create the ML tables (no layer-2 tables touched)

```bash
python -m ml_engine.migrate
```

## 2. Train & register the first models

```bash
# trains on the warehouse, prints metrics; --register logs + registers in MLflow
python -m ml_engine.models.classifier --train --register
```

The classifier module has a CLI; the retrain DAG (`ml_retrain_dag`) trains and
registers all four models weekly and promotes to **Production** only when the
primary metric improves. Inference always loads the latest Production model from
the registry — never a hardcoded pickle path.

## 3. Run inference

Via Airflow, `ml_inference` runs hourly:
`check_freshness → [classify | forecast + sla | cluster] → recommend → load`.

Ad-hoc, from a Python shell:

```python
from ml_engine.config import MLConfig
from ml_engine.data_access import read_tickets, get_engine
from ml_engine.models import classifier
from ml_engine import load

cfg = MLConfig.from_env(); df = read_tickets(cfg)
model = classifier.train(df, config=cfg)
preds = classifier.predict(model, df)
load.load_user_profiles(get_engine(cfg), preds)
```

## 4. Verify predictions landed in Postgres

```sql
SELECT profile, count(*) FROM ml_user_profiles GROUP BY profile;
SELECT * FROM ml_forecasts ORDER BY forecast_date LIMIT 10;
SELECT * FROM ml_sla_risk ORDER BY risk_score DESC LIMIT 10;
SELECT severity, count(*) FROM ml_clusters GROUP BY severity;
SELECT type, severity, title FROM recommendations ORDER BY created_at DESC LIMIT 20;
```

## 5. Open the MLflow UI

```bash
mlflow ui --backend-store-uri sqlite:///mlflow.db \
          --default-artifact-root ./mlartifacts    # local -> http://localhost:5000
```
Or with the stack up: the `mlflow-ui` compose service exposes it on
`http://localhost:5000`.

## 6. Tune recommendations

Edit `ml_engine/rules.yaml` (all thresholds live there — training concentration,
surcharge multiplier / SLA threshold, root-cause min tickets, repetitive count)
and re-run the `ml_inference` DAG. No code change needed.

## Tests

```bash
python -m pytest ml_engine/tests -q
```
All tests use small synthetic DataFrames — no live Postgres or GPU. Tests for
model paths that need heavy deps skip automatically when those deps are absent.
```
