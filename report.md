# Rapport technique — Architecture et fonctionnement de l'application

**Projet** : GlpiInteligence — plateforme d'intelligence du support informatique (Sartex Group)
**Périmètre** : analyse du dépôt `GlpiInteligence` (branche `main`, commit `62ca64f`)
**Date d'analyse** : 13 août 2026

> **Convention de fiabilité.** Chaque affirmation technique de ce rapport est rattachée à un
> fichier source du dépôt, indiqué sous la forme `Source : chemin/fichier.py`. Lorsqu'une
> information n'a pas pu être établie à partir du code, elle est explicitement signalée par
> la mention *« Cette information n'a pas pu être déterminée à partir du repository analysé. »*
> Aucune technologie n'est citée si elle n'est pas réellement présente dans le dépôt.

---

## 1. Introduction

Ce document décrit l'architecture, le fonctionnement interne et les flux de données de
l'application **GlpiInteligence**. Il s'adresse à un superviseur technique qui ne connaît pas
le projet et doit pouvoir, après lecture, suivre le parcours complet d'une donnée depuis
l'outil de gestion de parc **GLPI** jusqu'à son affichage dans le tableau de bord Angular
(Layer 5).

L'analyse a été menée exclusivement à partir du code du dépôt : fichiers source Python et
TypeScript, DDL SQL, DAGs Airflow, fichiers Docker, fichiers de configuration, dépendances et
tests. Le `README.md` du dépôt a servi de point d'entrée, mais chaque élément a été vérifié
dans le code correspondant.

### Structure du dépôt (racine)

```
GlpiInteligence/
├── glpi_connector/     Layer 1 — client REST GLPI + extracteurs
├── etl/                Layer 2 — transformation pandas + chargement PostgreSQL + DAG Airflow
├── ml_engine/          Layer 3 — moteur ML (4 modèles) + moteur de règles + DAGs Airflow
├── api/                Layer 4 — backend FastAPI (REST + WebSocket)
├── frontend/           Layer 5 — tableau de bord Angular 17
├── scripts/            outillage (test de connexion, peuplement GLPI, maintenance)
├── docker-compose.yml  orchestration des 9 services
├── Dockerfile.airflow  image commune Airflow / ETL / ML
├── Dockerfile.api      image dédiée du backend FastAPI
├── requirements.txt    dépendances Python des layers 1 à 4
├── .env.example        modèle de configuration (tous les layers)
└── README.md           documentation opérationnelle existante
```

`Source : arborescence du dépôt, docker-compose.yml`

---

## 2. Présentation générale du projet

GlpiInteligence est un **pipeline de données analytique et prédictif** construit **au-dessus**
d'une instance GLPI existante. GLPI reste le système opérationnel de gestion des tickets ; le
projet ne le modifie pas et ne s'y substitue pas : il **lit** GLPI via son API REST, construit
un entrepôt de données dédié, y applique des modèles d'apprentissage automatique, puis expose
les résultats à travers une API et un tableau de bord.

Le dépôt est organisé en **cinq couches numérotées** qui correspondent à cinq packages
distincts, chacun documenté par son propre en-tête de module :

| Couche | Package | Rôle déclaré dans le code |
| --- | --- | --- |
| Layer 1 | `glpi_connector/` | « Low-level GLPI REST client: session lifecycle, retries, pagination » |
| Layer 2 | `etl/` | « ETL & Real-Time Ingestion » — pandas + PostgreSQL + Airflow + Celery |
| Layer 3 | `ml_engine/` | « ML Engine (predictions & recommendations) » |
| Layer 4 | `api/` | « Layer 4 — REST + WebSocket backend for the IT dashboard » |
| Layer 5 | `frontend/` | SPA Angular 17 standalone |

`Source : glpi_connector/client.py, etl/dags/glpi_polling_dag.py (tags=["glpi","etl","layer2"]),
ml_engine/dags/ml_inference_dag.py (tags=["glpi","ml","layer3"]), api/main.py, frontend/package.json`

Les tags Airflow confirment la numérotation : le DAG d'ingestion porte `layer2`, les DAGs ML
portent `layer3`. La numérotation n'est donc pas seulement une convention de documentation,
elle est inscrite dans le code.

### Cloisonnement des couches (règle vérifiée dans le code)

Chaque couche n'écrit que dans son propre périmètre :

- Layer 2 écrit `dim_*` et `fact_kpis_daily` (`Source : etl/schema.sql`).
- Layer 3 écrit uniquement `ml_*` et `recommendations` — le fichier `ml_engine/schema.sql`
  porte le commentaire « Touches NONE of the layer-2 tables ».
- Layer 4 possède exactement deux tables, `api_users` et `recommendation_acks`
  (`Source : api/migrations/api_users_and_acks.sql`, commentaire « Touches NO layer-2/3 table »),
  et lit tout le reste.
- Layer 5 ne possède aucune base : elle ne consomme que l'API du Layer 4
  (`Source : frontend/src/app/core/services/api.service.ts`, `environment.ts`).

---

## 3. Objectifs de l'application

Les objectifs sont déductibles des sorties réellement produites par le code.

| Objectif | Réalisation concrète dans le code | Source |
| --- | --- | --- |
| Centraliser les données GLPI dans un entrepôt exploitable | Table `dim_tickets_enriched` + 4 dimensions + `fact_kpis_daily` | `etl/schema.sql` |
| Profiler les demandeurs (autonome / standard / dépendant / critique) | RandomForest sur 9 variables comportementales | `ml_engine/models/classifier.py` |
| Anticiper le volume de tickets à 72 h par catégorie | Prophet, repli sur moyenne glissante | `ml_engine/models/forecaster.py` |
| Anticiper le risque de non-respect du SLA à 48 h par technicien | XGBoost, repli sur taux historique | `ml_engine/models/sla_risk.py` |
| Détecter les causes racines récurrentes dans le texte français des tickets | spaCy + sentence-transformers + DBSCAN/K-Means | `ml_engine/models/clusterer.py` |
| Produire des recommandations actionnables pour la DSI | Moteur de règles YAML → 4 types de recommandations | `ml_engine/recommender.py`, `ml_engine/rules.yaml` |
| Exposer le tout à un tableau de bord temps réel | 13 routeurs FastAPI + WebSocket d'alertes | `api/routers/`, `api/alerts/broadcaster.py` |
| Offrir une consultation par rôle (DSI / MANAGER / DIRECTION) | JWT + `require_role(...)` | `api/security.py` |

Les quatre types de recommandations produits sont **FORMATION**, **SURCHARGE**,
**CAUSE_RACINE** et **AUTOMATISATION** (`Source : ml_engine/schema.sql`, `ml_engine/rules.yaml`,
`api/schemas/common.py::RecoType`).

---

## 4. Architecture globale

### 4.1 Nature de l'architecture

Il s'agit d'une **architecture en couches de type pipeline de données (ELT analytique)**,
et non d'une architecture applicative monolithique en couches. Les caractéristiques
observées dans le code :

- **Couplage par la base de données, pas par appel direct.** Layer 2 écrit dans PostgreSQL ;
  Layer 3 lit PostgreSQL et y réécrit ses résultats ; Layer 4 lit PostgreSQL. Aucun de ces
  trois composants ne s'appelle mutuellement par HTTP.
  `Source : etl/load.py`, `ml_engine/data_access.py`, `api/database.py`
- **Une seule frontière HTTP synchrone en aval** : Layer 5 → Layer 4 (REST + WebSocket).
  `Source : frontend/src/app/core/services/api.service.ts`
- **Une seule frontière HTTP en amont** : Layer 1 → GLPI (REST).
  `Source : glpi_connector/client.py`
- **Deux ordonnanceurs Airflow distincts** : `glpi_polling` (toutes les 10 minutes) et
  `ml_inference` (toutes les heures) + `ml_retrain` (hebdomadaire).
- **Isolation des dépendances par image Docker** : l'API a sa propre image parce qu'elle exige
  SQLAlchemy 2.x + asyncpg, incompatible avec le SQLAlchemy 1.4 imposé par Airflow 2.9.3.
  `Source : Dockerfile.api` (commentaire explicite), `api/requirements-api.txt`

### 4.2 Diagramme d'architecture principal

```mermaid
flowchart TD
    subgraph SRC["SOURCE"]
        GLPI["<b>GLPI</b><br/>API REST<br/>Tickets, Users, Entities,<br/>ITILCategory, Group, ITILFollowup"]
    end

    subgraph L1["LAYER 1 — glpi_connector/"]
        CLIENT["GLPIClient<br/>client.py<br/>session, retries, pagination"]
        EXTRACT["extractors.py<br/>extract_tickets / users /<br/>entities / categories /<br/>groups / followups"]
        CLIENT --> EXTRACT
    end

    subgraph L2["LAYER 2 — etl/"]
        DAG1["DAG glpi_polling<br/>*/10 * * * *"]
        TRANS["TicketTransformer<br/>transform.py (pandas)"]
        LOAD["load.py<br/>upsert via tables de staging"]
        CEL["Celery worker<br/>tasks.py"]
        DAG1 --> CEL
        CEL --> TRANS
        CEL --> LOAD
    end

    subgraph DB["POSTGRESQL — base glpi_dw"]
        DIM["dim_tickets_enriched<br/>dim_users / dim_entities<br/>dim_categories / dim_groups<br/>fact_kpis_daily"]
        MLT["ml_user_profiles<br/>ml_forecasts / ml_sla_risk<br/>ml_clusters / recommendations"]
        APIT["api_users<br/>recommendation_acks"]
    end

    subgraph L3["LAYER 3 — ml_engine/"]
        DAG2["DAG ml_inference (horaire)<br/>DAG ml_retrain (hebdo)"]
        M1["classifier.py<br/>RandomForest"]
        M2["forecaster.py<br/>Prophet"]
        M3["sla_risk.py<br/>XGBoost"]
        M4["clusterer.py<br/>spaCy + embeddings<br/>+ DBSCAN/KMeans"]
        RECO["recommender.py<br/>+ rules.yaml"]
        MLF["MLflow<br/>registre de modèles"]
        DAG2 --> M1 & M2 & M3 & M4
        M1 & M2 & M3 & M4 --> RECO
        M1 & M3 -.->|"charge/enregistre"| MLF
    end

    subgraph L4["LAYER 4 — api/"]
        FAPI["FastAPI<br/>main.py"]
        RT["routers/ — 13 modules"]
        QRY["queries/ — SQL"]
        BC["alerts/broadcaster.py<br/>sondage 10 s"]
        RDS["Redis<br/>cache 60 s / 300 s"]
        FAPI --> RT --> QRY
        FAPI --> BC
        RT --> RDS
    end

    subgraph L5["LAYER 5 — frontend/"]
        NG["Angular 17 standalone<br/>7 onglets analytiques"]
        SVC["ApiService / DashboardService<br/>AuthService / WebsocketService"]
        NG --> SVC
    end

    GLPI -->|"HTTPS REST<br/>App-Token + Session-Token"| CLIENT
    EXTRACT -->|"list[dict] via XCom"| DAG1
    LOAD -->|"INSERT ... ON CONFLICT"| DIM
    DIM -->|"SELECT * (pandas.read_sql)"| DAG2
    RECO -->|"upsert JSONB"| MLT
    DIM --> QRY
    MLT --> QRY
    APIT --> QRY
    MLT -->|"polling CRITIQUE"| BC
    QRY -->|"JSON REST"| SVC
    BC -->|"WebSocket /ws/alerts"| SVC
```

### 4.3 Vue infrastructure (docker-compose)

Neuf services sont définis. `Source : docker-compose.yml`

| Service | Image | Port publié | Rôle |
| --- | --- | --- | --- |
| `postgres` | `postgres:16-alpine` | 5432 | Métabase Airflow (`airflow`) **et** entrepôt (`glpi_dw`) |
| `redis` | `redis:7-alpine` | 6379 | db 0 = cache ETL/API, db 1 = broker Celery Airflow |
| `airflow-init` | `glpi-airflow:local` | — | `airflow db migrate` + création de l'utilisateur `admin` |
| `airflow-webserver` | `glpi-airflow:local` | 8080 | Interface Airflow |
| `airflow-scheduler` | `glpi-airflow:local` | — | Ordonnanceur |
| `airflow-worker` | `glpi-airflow:local` | — | Worker Celery Airflow |
| `glpi-etl-worker` | `glpi-airflow:local` | — | Worker Celery dédié à `etl.tasks` (file `celery`) |
| `mlflow-ui` | `glpi-airflow:local` | 5000 | Interface MLflow (backend SQLite partagé) |
| `api` | `glpi-api:local` | 8000 | Backend FastAPI (Layer 4) |

Le frontend (Layer 5) **n'est pas conteneurisé** : il n'apparaît pas dans `docker-compose.yml`
et se lance via `npm start` (`ng serve`, port 4200). `Source : frontend/package.json`

Volumes nommés : `postgres-data`, `airflow-logs`, `mlruns`. Le volume `mlruns` est partagé
entre tous les conteneurs Airflow et l'interface MLflow.

---

## 5. Vue d'ensemble GLPI → Layer 1 → Layer 2 → Layer 3 → Layer 4 → Layer 5

```mermaid
flowchart TD
    G["<b>GLPI</b><br/><i>Système source</i><br/>API REST /apirest.php ou /api.php/v1"]
    L1["<b>LAYER 1 — glpi_connector</b><br/><i>Extraction</i><br/>GLPIClient + 6 extracteurs<br/>Sortie : list[dict] à noms lisibles"]
    L2["<b>LAYER 2 — etl</b><br/><i>Transformation & chargement</i><br/>Airflow 10 min + Celery + pandas<br/>Sortie : dim_* + fact_kpis_daily"]
    L3["<b>LAYER 3 — ml_engine</b><br/><i>Intelligence</i><br/>4 modèles + moteur de règles<br/>Sortie : ml_* + recommendations"]
    L4["<b>LAYER 4 — api</b><br/><i>Service</i><br/>FastAPI async + Redis + JWT<br/>Sortie : JSON REST + WebSocket"]
    L5["<b>LAYER 5 — frontend</b><br/><i>Restitution</i><br/>Angular 17 + Chart.js<br/>Sortie : 7 onglets + alertes temps réel"]

    G -->|"HTTP GET /search/Ticket<br/>HTTP GET /{itemtype}"| L1
    L1 -->|"list[dict] (XCom Airflow)"| L2
    L2 -->|"PostgreSQL glpi_dw<br/>lecture SQL"| L3
    L3 -->|"PostgreSQL glpi_dw<br/>lecture SQL"| L4
    L4 -->|"HTTP JSON + WS<br/>Bearer JWT"| L5
```

**Point d'architecture essentiel** : les échanges L2 → L3 → L4 **ne sont pas des appels
réseau**. Ils passent par la base `glpi_dw`, qui joue le rôle de bus d'intégration. Cela
implique qu'aucune de ces couches n'a besoin que la suivante soit démarrée pour fonctionner,
et que le contrat d'interface entre elles est le **schéma SQL**, pas une signature d'API.

`Source : etl/load.py`, `ml_engine/data_access.py::read_tickets`, `api/queries/*.py`

---

## 6. Layer 1 — `glpi_connector/` — Extraction depuis GLPI

### 6.1 Objectif

Fournir une extraction fiable et paginée des données GLPI via son API REST, et restituer des
dictionnaires Python propres avec des noms de champs lisibles, consommables par les couches
suivantes. C'est la **seule** couche qui parle à GLPI.

> « Reliable, paginated extraction of GLPI data via the REST API. […] It produces clean Python
> dicts that the downstream layers (Airflow ETL, ML engine, FastAPI backend) consume. »
> `Source : README.md`

### 6.2 Architecture

```mermaid
flowchart LR
    ENV[".env<br/>GLPI_BASE_URL<br/>GLPI_APP_TOKEN<br/>GLPI_USER_TOKEN"]
    CFG["GLPIConfig.from_env()<br/>config.py"]
    CLI["GLPIClient<br/>client.py"]
    EXC["exceptions.py<br/>GLPIAPIError et sous-classes"]
    EXT["extractors.py"]
    OUT["list[dict]"]

    ENV --> CFG --> CLI
    CLI -.->|"lève"| EXC
    CLI --> EXT --> OUT
```

### 6.3 Composants

| Fichier | Composant | Rôle |
| --- | --- | --- |
| `config.py` | `GLPIConfig` (dataclass gelée) | Configuration lue depuis l'environnement, avec validation des 3 variables obligatoires |
| `client.py` | `GLPIClient` | Cycle de session, réessais, pagination, en-têtes d'authentification |
| `extractors.py` | `TICKET_FIELD_MAP` + 6 fonctions | Traduction des identifiants numériques GLPI en noms de champs lisibles |
| `exceptions.py` | 5 classes d'exception | Typage des erreurs GLPI |
| `tests/` | 12 tests pytest | Tests avec `requests-mock`, sans réseau |

### 6.4 Fichiers et fonctions clés

**`GLPIConfig.from_env()`** — `Source : glpi_connector/config.py`
Charge `.env` via `python-dotenv` puis lit `GLPI_BASE_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN`.
Si l'une des trois manque, lève `RuntimeError` avec la liste des variables absentes.
Paramètres optionnels et leurs valeurs par défaut : `page_size=100`, `request_timeout=30.0`,
`max_retries=3`, `retry_backoff=1.5`, `verify_ssl=True`.

**`GLPIClient`** — `Source : glpi_connector/client.py`

- `__enter__` / `__exit__` : gestionnaire de contexte garantissant que `killSession` est
  toujours appelé, même en cas d'exception.
- `init_session()` : `GET {base_url}/initSession` avec les en-têtes
  `App-Token` et `Authorization: user_token <token>`. Récupère `session_token` du corps JSON.
  Un `401` lève `GLPIAuthError` ; l'absence de `session_token` également.
- `kill_session()` : `GET {base_url}/killSession`, remise à `None` du jeton dans un `finally`.
- `_auth_headers()` : construit `App-Token` + `Session-Token` ; lève `GLPISessionExpired` si
  aucune session n'est ouverte.
- `_request()` : cœur de la robustesse (voir § 6.9).
- `get_item(itemtype, id)` : `GET /{itemtype}/{id}` avec `expand_dropdowns`.
- `list_items(itemtype)` : pagination simple par `range=start-end` ; s'arrête quand un lot est
  vide, non-liste, ou plus petit que la taille demandée. Utilisé pour les petites tables de
  référence.
- `search(itemtype, forcedisplay, criteria)` : **générateur** paginant `/search/{itemtype}`.
  Il émet une ligne brute à la fois.

**Détail de pagination critique** (`Source : glpi_connector/client.py`, commentaire dans le code) :
l'avancement se fait par `start += len(data)` et **jamais** par `start += size`. GLPI applique
un plafond global (`list_limit_max`, souvent 500) qui tronque la dernière page ; faire
confiance à `size` provoquerait le saut silencieux du reste du jeu de données.

**`extractors.py`** — `Source : glpi_connector/extractors.py`

`TICKET_FIELD_MAP` mappe 19 identifiants d'options de recherche GLPI vers des noms lisibles :

| ID | Nom | ID | Nom | ID | Nom |
| --- | --- | --- | --- | --- | --- |
| 2 | `id` | 15 | `date` | 5 | `_users_id_assign` |
| 1 | `name` | 19 | `date_mod` | 80 | `entities_id` |
| 21 | `content` | 17 | `solvedate` | 71 | `_groups_id_requester` |
| 12 | `status` | 16 | `closedate` | 10 | `urgency` |
| 14 | `type` | 18 | `time_to_resolve` | 11 | `impact` |
| 3 | `priority` | 4 | `_users_id_requester` | | |
| 7 | `itilcategories_id` | | | | |

Six extracteurs sont fournis : `extract_tickets`, `extract_users`, `extract_entities`,
`extract_categories`, `extract_groups`, `extract_ticket_followups`.

`extract_ticket_followups` gère la variabilité de version : il tente `ITILFollowup` (GLPI 10+)
et bascule sur `TicketFollowup` (GLPI 9.x) en cas d'échec. Il normalise également `tickets_id`
à partir de `items_id` quand `itemtype == "Ticket"`.

### 6.5 Fonctionnement étape par étape

1. `GLPIConfig.from_env()` lit `.env` et valide les trois secrets.
2. `with GLPIClient(config) as client:` → `initSession` ouvre la session, GLPI renvoie un
   `session_token`.
3. Pour les tickets : `client.search("Ticket", forcedisplay=[1,2,3,4,5,7,10,11,12,14,15,16,17,18,19,21,71,80])`.
   Le paramètre `forcedisplay` sélectionne les colonnes en amont — c'est le mode le plus
   efficace car il évite les recherches en cascade côté GLPI pour le demandeur, l'affecté, etc.
4. GLPI renvoie un JSON `{"data": [...], "totalcount": N}` ; les clés des lignes sont les
   identifiants d'options **sous forme de chaînes** (`"2"`, `"12"`, …).
5. `_remap()` traduit chaque ligne en dictionnaire à clés lisibles.
6. Pour les tables de référence : `list_items` avec `expand_dropdowns=true`, puis `_slim()`
   ne conserve que les clés utiles.
7. À la sortie du bloc `with`, `killSession` libère la session côté GLPI.

### 6.6 Entrées

| Entrée | Origine | Format |
| --- | --- | --- |
| `GLPI_BASE_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN` | `.env` ou variables d'environnement (injectées par compose ou hydratées depuis les Variables Airflow) | chaînes |
| Réponses HTTP GLPI | API REST GLPI | JSON |

### 6.7 Sorties

| Fonction | Sortie | Clés produites |
| --- | --- | --- |
| `extract_tickets` | `list[dict]` | les 19 noms de `TICKET_FIELD_MAP` |
| `extract_users` | `list[dict]` | `id, name, realname, firstname, is_active, entities_id, groups_id` |
| `extract_entities` | `list[dict]` | `id, name, completename, entities_id, level` |
| `extract_categories` | `list[dict]` | `id, name, completename, itilcategories_id` |
| `extract_groups` | `list[dict]` | `id, name, completename, groups_id, entities_id` |
| `extract_ticket_followups` | `list[dict]` | `id, items_id, tickets_id, itemtype, content, date, users_id` |

### 6.8 Communications

**GLPI → Layer 1**

| Élément | Valeur |
| --- | --- |
| Protocole | HTTP/HTTPS (bibliothèque `requests`) |
| Endpoints | `/initSession`, `/killSession`, `/search/{itemtype}`, `/{itemtype}`, `/{itemtype}/{id}` |
| Méthode | `GET` exclusivement (le connecteur est en lecture seule) |
| Authentification | En-tête `App-Token` + `Authorization: user_token <token>` à l'ouverture, puis `App-Token` + `Session-Token` |
| Format | JSON |
| Vérification TLS | `verify_ssl`, activée par défaut |

**Layer 1 → Layer 2** : import Python direct. Le DAG importe
`from glpi_connector.client import GLPIClient` et `from glpi_connector.extractors import ...`
à l'intérieur des tâches. `Source : etl/dags/glpi_polling_dag.py`

### 6.9 Gestion des erreurs

`_request()` implémente une boucle de `max_retries` tentatives (3 par défaut) avec un délai
exponentiel `retry_backoff ** attempt` (1,5^n) :

| Situation | Comportement | Exception finale |
| --- | --- | --- |
| `requests.RequestException` (réseau) | attente puis nouvelle tentative | `GLPIUnavailable` |
| HTTP 401 sur une requête | **réouverture transparente de la session**, puis nouvelle tentative | — |
| HTTP 429 | attente puis nouvelle tentative ; à la dernière tentative → levée | `GLPIRateLimited` |
| HTTP ≥ 500 | attente puis nouvelle tentative | `GLPIAPIError` |
| Autre statut non-OK | levée immédiate, sans réessai | `GLPIAPIError` |
| `initSession` en 401 | levée immédiate | `GLPIAuthError` |

Hiérarchie d'exceptions (`Source : glpi_connector/exceptions.py`) :
`GLPIAPIError` (base, porte `status_code` et `payload`) → `GLPIAuthError`,
`GLPISessionExpired`, `GLPIRateLimited`, `GLPIUnavailable`.

**Journalisation** : chaque module utilise `logging.getLogger(__name__)`. Le client journalise
en `INFO` l'ouverture et la fermeture de session ainsi que la fin de pagination, en `WARNING`
chaque réessai (avec la cause et le délai), et en `DEBUG` la progression page par page. Les
extracteurs journalisent en `INFO` le nombre de lignes extraites.

### 6.10 Configuration

Variables reconnues (`Source : glpi_connector/config.py`, `.env.example`) :
`GLPI_BASE_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN` (obligatoires), `GLPI_PAGE_SIZE`,
`GLPI_TIMEOUT`, `GLPI_MAX_RETRIES`, `GLPI_RETRY_BACKOFF`, `GLPI_VERIFY_SSL`.

Le chemin de base dépend de la version majeure de GLPI : `/apirest.php` pour GLPI 9.x/10.x,
`/api.php/v1` pour GLPI 11.x. `Source : .env.example`, `README.md`

En contexte conteneurisé, `docker-compose.yml` injecte
`GLPI_BASE_URL: ${GLPI_BASE_URL_CONTAINER:-http://host.docker.internal:8080/api.php/v1}` car
`127.0.0.1` désignerait le conteneur lui-même.


---

## 7. Layer 2 — `etl/` — Transformation et entrepôt de données

### 7.1 Objectif

Interroger GLPI toutes les 10 minutes via le Layer 1, nettoyer et enrichir les tickets avec
pandas, résoudre les clés étrangères, puis alimenter de façon idempotente l'entrepôt
PostgreSQL `glpi_dw`. C'est la couche qui transforme un flux d'API en modèle dimensionnel.

### 7.2 Architecture

```mermaid
flowchart TD
    subgraph AF["Airflow — DAG glpi_polling (*/10 * * * *)"]
        T1["extract_tickets_task"]
        T2["extract_dims_task"]
        T3["extract_followups_task"]
        T4["transform_task"]
        T5["load_postgres_task"]
    end
    subgraph CW["Worker Celery — glpi-etl-worker"]
        C1["etl.transform_tickets"]
        C2["etl.load_dimensions"]
        C3["etl.load_tickets"]
        C4["etl.load_kpis"]
    end
    subgraph PG["PostgreSQL glpi_dw"]
        D1["dim_users / dim_entities<br/>dim_categories / dim_groups"]
        D2["dim_tickets_enriched"]
        D3["fact_kpis_daily"]
    end
    RED["Redis db 0<br/>broker + backend Celery"]

    T1 --> T4
    T2 --> T4
    T3 --> T4
    T4 -->|".delay()"| RED --> C1
    C1 -->|"TicketTransformer"| T4
    T4 --> T5
    T5 -->|"1. dimensions d'abord"| C2 --> D1
    T5 -->|"2. puis tickets"| C3 --> D2
    T5 -->|"3. puis KPI du jour"| C4 --> D3
    D1 -.->|"résolution des libellés<br/>en identifiants"| C3
```

### 7.3 Composants

| Fichier | Composant | Rôle |
| --- | --- | --- |
| `config.py` | `get_glpi_config()`, `ETLConfig` | Hydratation depuis les Variables Airflow ; URLs PostgreSQL et Redis |
| `cache.py` | `GLPICache` | Cache Redis JSON à deux paliers de TTL |
| `tasks.py` | `celery_app` + 4 tâches | Application Celery et tâches lourdes |
| `transform.py` | `TicketTransformer`, `flatten_glpi_value`, `normalize_title` | Transformation pandas pure, sans dépendance Airflow/DB |
| `load.py` | `load_tickets`, `load_dimension`, `load_daily_kpis`, `resolve_fk_display_names` | Chargement idempotent SQLAlchemy |
| `schema.sql` | DDL | 6 tables + 4 index |
| `dags/glpi_polling_dag.py` | DAG TaskFlow | Orchestration |
| `tests/` | 11 tests | transform, cache (fakeredis), load (SQLite) |

### 7.4 Configuration

`get_glpi_config()` appelle d'abord `_hydrate_from_airflow()`, qui copie les Variables Airflow
`GLPI_BASE_URL`, `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN` dans `os.environ` **uniquement si elles
n'y sont pas déjà**. `Source : etl/config.py`

**Conséquence importante** : sous docker-compose, ces trois variables sont injectées dans
l'environnement de tous les conteneurs Airflow ; modifier la Variable Airflow n'a donc **aucun
effet**. Il faut modifier `.env` et recréer les services concernés.

`ETLConfig.from_env()` lit `POSTGRES_URL`
(défaut `postgresql+psycopg2://glpi:glpi@postgres:5432/glpi_dw`), `REDIS_URL`
(défaut `redis://redis:6379/0`), `CACHE_TTL_LIVE` (300 s) et `CACHE_TTL_AGG` (3600 s).

### 7.5 Le DAG `glpi_polling`

`Source : etl/dags/glpi_polling_dag.py`

| Paramètre | Valeur |
| --- | --- |
| `dag_id` | `glpi_polling` |
| `schedule` | `*/10 * * * *` (toutes les 10 minutes) |
| `start_date` | 1er janvier 2026 |
| `catchup` | `False` |
| `max_active_runs` | 1 |
| `retries` / `retry_delay` | 2 / 2 minutes |
| `tags` | `["glpi", "etl", "layer2"]` |
| `CELERY_TIMEOUT` | 600 s d'attente sur un `AsyncResult` |

Cinq tâches :

1. **`extract_tickets_task`** — ouvre un `GLPIClient`, appelle `extract_tickets`, renvoie la
   liste des tickets (transitant par XCom).
2. **`extract_dims_task`** — ouvre un `GLPIClient` et construit un dictionnaire
   `{"dim_users": …, "dim_entities": …, "dim_categories": …, "dim_groups": …}`.
3. **`extract_followups_task`** — extrait les suivis ITIL.
4. **`transform_task`** — délègue à Celery (`transform_tickets_task.delay(tickets)`) et attend
   le résultat. Ajoute `dims` (transmis tel quel) et `followup_count` au dictionnaire de sortie.
5. **`load_postgres_task`** — orchestre trois tâches Celery **dans un ordre imposé**.

**Règle d'ordonnancement critique** (`Source : etl/dags/glpi_polling_dag.py`, commentaire du
code) : `load_dimensions_task` s'exécute **avant** `load_tickets_task`, parce que le chargeur
de tickets résout les libellés d'affichage GLPI (« Root entity > Usine A ») en identifiants
contre ces tables de dimensions. Inverser l'ordre mettrait silencieusement toutes les clés
étrangères à `NULL`.

**Normalisation de la date d'exécution** : `_to_day_iso()` accepte `None`, une chaîne, ou un
objet `pendulum.DateTime` injecté par Airflow, et renvoie toujours `YYYY-MM-DD`. Un simple
découpage de chaîne lèverait `TypeError` sur l'objet pendulum.

### 7.6 Les tâches Celery

`Source : etl/tasks.py`

L'application Celery s'appelle `glpi_etl`, broker et backend pointant sur `REDIS_URL`.
Configuration : sérialisation JSON, `task_acks_late=True`, `worker_prefetch_multiplier=1`.

| Tâche | Nom Celery | Entrée | Sortie |
| --- | --- | --- | --- |
| `transform_tickets_task` | `etl.transform_tickets` | `list[dict]` brut | `{records, kpis, row_count}` |
| `load_tickets_task` | `etl.load_tickets` | `list[dict]` transformé | nombre de lignes chargées |
| `load_dimensions_task` | `etl.load_dimensions` | `{table: rows}` | `{table: count}` |
| `load_kpis_task` | `etl.load_kpis` | `(kpis, day_iso)` | date ISO |

`transform_tickets_task` sérialise les colonnes temporelles en chaînes ISO
`%Y-%m-%d %H:%M:%S` pour que le résultat soit transportable en JSON via Redis ;
`load_tickets_task` les reconvertit avec `pd.to_datetime`.

### 7.7 La transformation pandas

`Source : etl/transform.py` — module **sans aucun import Airflow, Celery ou base de données**,
donc testable isolément.

**`RAW_TO_CANONICAL`** renomme les champs à préfixe underscore issus des options privées GLPI :
`_users_id_requester` → `user_requester`, `_users_id_assign` → `user_assign`,
`_groups_id_requester` → `groups_id_requester`. Les 16 autres champs conservent leur nom.

**Pipeline `TicketTransformer.transform()`** — quatre étapes séquentielles :

1. **`to_dataframe()`** — construit le DataFrame, renomme les colonnes connues, **supprime les
   colonnes inconnues** pour stabiliser le schéma, et crée en `pd.NA` toute colonne canonique
   absente. Sur une entrée vide, renvoie un DataFrame vide mais correctement colonné.
2. **`parse_dates()`** — `pd.to_datetime(errors="coerce")` sur `date`, `date_mod`, `solvedate`,
   `closedate`, `time_to_resolve`.
3. **`coerce_fk_ids()`** — étape la plus délicate (voir § 7.8).
4. **`add_derived()`** — calcule quatre colonnes dérivées :
   - `is_resolved` = `status ∈ {5, 6}` (5 = résolu, 6 = clos)
   - `is_high_priority` = `priority ∈ {5, 6}` (5 = très haute, 6 = majeure)
   - `resolution_days` = `(solvedate − date)` en jours décimaux
   - `name_normalized` = titre en minuscules, préfixes `re:`, `tr:`, `fwd:`, `fw:` retirés de
     façon répétée (`normalize_title`)

**`flatten_glpi_value()`** réduit une cellule GLPI à un scalaire : une option de recherche
multivaluée revient sous forme de liste (un ticket peut avoir plusieurs demandeurs), parfois de
dictionnaires `{"name": …}`. La fonction descend récursivement et retient la première valeur
non vide, ou `id`/`name`/`completename` pour un dictionnaire.

**`compute_kpis()`** (statique) produit quatre indicateurs :
`total_tickets`, `resolved_pct` (%), `high_priority_count`, `avg_resolution_days` (moyenne sur
les seuls tickets résolus). Sur DataFrame vide, renvoie des zéros.

### 7.8 Le mécanisme de résolution des clés étrangères

C'est le point technique le plus subtil de la couche, documenté à la fois dans le code et le
README.

**Le problème** : `/search/Ticket` renvoie des **libellés d'affichage**, pas des identifiants,
pour toute colonne adossée à une liste déroulante. `entities_id` revient sous la forme
`"Root entity > Usine A"`, pas `2`. Or les colonnes de l'entrepôt sont de type `BIGINT`.

**La solution en deux temps** :

1. **Côté transformation** (`coerce_fk_ids`, `Source : etl/transform.py`) : pour chacune des
   5 colonnes de `FK_COLUMNS` (`itilcategories_id`, `entities_id`, `groups_id_requester`,
   `user_requester`, `user_assign`), la valeur aplatie est **conservée** dans une colonne
   `<col>_display` de type chaîne, tandis que la colonne numérique est passée en `Int64` avec
   `errors="coerce"` — donc `NA` pour les libellés.

2. **Côté chargement** (`resolve_fk_display_names`, `Source : etl/load.py`) : pour chaque
   colonne encore `NA` mais dont le `_display` est renseigné, un dictionnaire
   `{libellé normalisé → id}` est construit à partir de la table de dimension correspondante
   (`FK_RESOLUTION`), puis appliqué.

**Construction du dictionnaire de correspondance** (`_lookup_map`) : plusieurs orthographes
sont indexées par ligne, car l'affichage retenu dépend des préférences de l'instance GLPI :
- pour `dim_users` : `"realname firstname"`, `"firstname realname"`, puis `name` ;
- pour les autres : `completename`, `name`, et la **feuille** d'un chemin `A > B > C`.

La normalisation `_norm()` réduit la casse, comprime les espaces, uniformise le séparateur
` > `, et rejette `nan`/`none`/`<na>`. Le premier écrivain gagne (`if k not in out`).

**Traçabilité** : le taux de résolution est journalisé
(`resolve_fk: %s -> %s resolved %d/%d (%d unmatched)`), et jusqu'à 5 exemples non résolus sont
émis en `WARNING`. Si la table de dimension est vide, un avertissement explicite rappelle qu'il
faut charger les dimensions avant les tickets.

**Anti-pattern documenté dans le README** : « Never "fix" a datatype mismatch with a bare
`pd.to_numeric(..., errors='coerce')` on these columns. It satisfies the `BIGINT` type by
throwing the value away — the tickets load fine and every category/site/user link is quietly
`NULL`. »

### 7.9 Le chargement PostgreSQL

`Source : etl/load.py`

**`_upsert_via_staging()`** — motif unique réutilisé partout :

```
DROP TABLE IF EXISTS _stg_<table>
payload.head(0).to_sql(...)        -- crée la table de staging typée par pandas
payload.to_sql(..., append)        -- insère les données
INSERT INTO <table> (cols) SELECT cols FROM _stg_<table> WHERE true
  ON CONFLICT (<pk>) DO UPDATE SET col=EXCLUDED.col, ...
DROP TABLE _stg_<table>
```

L'opération est **idempotente** : rejouer le DAG ne duplique rien, il met à jour.

**`DIM_COLUMN_CASTS`** — pandas déduit le type de la table de staging à partir du DataFrame.
Comme GLPI renvoie `0`/`1` pour les booléens, la colonne de staging serait `BIGINT` et
l'insertion vers une colonne `BOOLEAN` échouerait avec
`column "is_active" is of type boolean but expression is of type bigint`. Le dictionnaire
`DIM_COLUMN_CASTS` déclare donc explicitement le type cible de chaque colonne de dimension
(`int`, `bool`, `str`), appliqué par `_coerce_dim_types()` avec les fonctions utilitaires
`_to_bool` (reconnaissant `1/true/t/yes/y/on` et `0/false/f/no/n/off/""/none/nan`) et
`flatten_glpi_value`.

**`load_daily_kpis()`** — `INSERT … ON CONFLICT (date) DO UPDATE` sur `fact_kpis_daily`, avec
mise à jour de `computed_at = NOW()`.

**`ensure_schema()`** — exécute `schema.sql` instruction par instruction (découpage sur `;`)
afin de rester compatible avec SQLite, utilisé dans les tests.

### 7.10 Le schéma de l'entrepôt

`Source : etl/schema.sql` — DDL idempotent (`CREATE TABLE IF NOT EXISTS`).

**`dim_tickets_enriched`** — table de faits centrale, 23 colonnes :

| Colonne | Type | Origine |
| --- | --- | --- |
| `id` | `BIGINT PRIMARY KEY` | GLPI |
| `name`, `content` | `TEXT` | GLPI |
| `status`, `type`, `priority`, `urgency`, `impact` | `INTEGER` | GLPI |
| `itilcategories_id`, `user_requester`, `user_assign`, `entities_id`, `groups_id_requester` | `BIGINT` | résolu par Layer 2 |
| `date`, `date_mod`, `solvedate`, `closedate`, `time_to_resolve` | `TIMESTAMP` | GLPI |
| `is_resolved`, `is_high_priority` | `BOOLEAN` | **dérivé Layer 2** |
| `resolution_days` | `DOUBLE PRECISION` | **dérivé Layer 2** |
| `name_normalized` | `TEXT` | **dérivé Layer 2** |
| `loaded_at` | `TIMESTAMP DEFAULT NOW()` | Layer 2 |

Index : `idx_tickets_status`, `idx_tickets_entity`, `idx_tickets_category`,
`idx_tickets_normalized`.

**Dimensions** : `dim_users` (7 colonnes), `dim_entities` (5), `dim_categories` (4),
`dim_groups` (5), toutes avec `id BIGINT PRIMARY KEY` et `loaded_at`.

**`fact_kpis_daily`** : `date DATE PRIMARY KEY`, `total_tickets`, `resolved_pct`,
`high_priority_count`, `avg_resolution_days`, `computed_at`.

**Remarque de modélisation importante** : `time_to_resolve` est un `TIMESTAMP` — c'est une
**échéance SLA**, pas une durée. Cette convention est réutilisée telle quelle en Layer 3 et
Layer 4. `Source : api/queries/shared.py` (docstring explicite)

### 7.11 Le cache Redis

`Source : etl/cache.py`

`GLPICache` encapsule Redis avec un espace de noms `glpi:<tier>:<clé>` et deux paliers de TTL :
`live` (300 s) et `aggregate` (3600 s). Méthodes : `get`, `set` (via `SETEX`), `invalidate`,
`stats` (compteurs `hits`/`misses`). Les valeurs sont sérialisées en JSON avec `default=str`.

*Observation issue de l'analyse du code* : ce cache est fourni et testé
(`etl/tests/test_cache.py`, avec `fakeredis`), mais aucun appel à `GLPICache` n'apparaît dans
`tasks.py`, `load.py`, `transform.py` ni dans le DAG. C'est donc un composant disponible mais
non branché dans le flux d'ingestion actuel. Le cache réellement actif sur le chemin des données
est celui du Layer 4 (`api/cache.py`). Redis, lui, est bien utilisé en Layer 2 comme broker et
backend Celery.

### 7.12 Entrées / Sorties

| | Entrée | Sortie |
| --- | --- | --- |
| **Données** | `list[dict]` du Layer 1 | Lignes dans `dim_tickets_enriched`, `dim_users`, `dim_entities`, `dim_categories`, `dim_groups`, `fact_kpis_daily` |
| **Configuration** | `POSTGRES_URL`, `REDIS_URL`, variables `GLPI_*` | — |
| **Transport interne** | XCom Airflow (entre tâches), Redis (Celery) | — |

### 7.13 Gestion des erreurs et journalisation

- **Au niveau Airflow** : `retries=2`, `retry_delay=2 min`, `max_active_runs=1`.
- **Au niveau Celery** : `task_acks_late=True` (la tâche n'est acquittée qu'après exécution,
  donc une mort de worker la fait rejouer) ; `_wait_celery` impose un délai maximal de 600 s.
- **Au niveau résolution de FK** : les échecs de lecture d'une table de dimension sont
  interceptés (`except Exception`) et journalisés en `WARNING` sans interrompre le chargement ;
  les lignes non résolues restent `NA` et sont comptabilisées.
- **Journalisation** : `logger.info` pour les volumes chargés (`load: upserted %d rows into %s`),
  `logger.warning` pour les résolutions partielles, `logger.info("load summary: %s")` en fin de
  DAG.

Le README documente en outre les modes de défaillance opérationnels observés : exécution
`running` orpheline bloquant la suivante sous `max_active_runs=1`, code de sortie 1 sans trace
Python (arrêt par le tueur OOM), tâche bloquée en `queued`.

---

## 8. Layer 3 — `ml_engine/` — Moteur d'intelligence artificielle

### 8.1 Objectif

Lire l'entrepôt propre produit par le Layer 2, entraîner et appliquer **quatre familles de
modèles**, en dériver des **recommandations actionnables** par moteur de règles, et réécrire le
tout dans de nouvelles tables `ml_*` et `recommendations`. La couche ne modifie rien des
Layers 1 et 2.

### 8.2 Architecture

```mermaid
flowchart TD
    PG[("dim_tickets_enriched")]
    DA["data_access.py<br/>read_tickets / count_recent_tickets"]
    FE["features.py<br/>build_user_features<br/>build_daily_category_counts<br/>build_sla_features<br/>build_text_corpus"]

    C["classifier.py<br/><b>RandomForest</b><br/>4 profils utilisateurs"]
    F["forecaster.py<br/><b>Prophet</b><br/>volume 72 h / catégorie"]
    S["sla_risk.py<br/><b>XGBoost</b><br/>risque SLA 48 h / technicien"]
    K["clusterer.py<br/><b>spaCy + embeddings<br/>+ DBSCAN/KMeans</b>"]

    R["recommender.py<br/>+ rules.yaml"]
    L["load.py<br/>upsert JSONB"]
    REG["registry.py<br/>MLflow"]

    OUT[("ml_user_profiles<br/>ml_forecasts<br/>ml_sla_risk<br/>ml_clusters<br/>recommendations")]

    PG --> DA --> FE
    FE --> C
    FE --> F
    FE --> S
    FE --> K
    C --> R
    F --> R
    S --> R
    K --> R
    R --> L --> OUT
    C --> L
    F --> L
    S --> L
    K --> L
    C <-.-> REG
    S <-.-> REG
```

### 8.3 Composants

| Fichier | Rôle | Dépendance lourde |
| --- | --- | --- |
| `config.py` | `MLConfig.from_env()` | aucune |
| `data_access.py` | lecture de `dim_tickets_enriched`, contrôle de fraîcheur | SQLAlchemy |
| `features.py` | ingénierie de variables — **pandas pur, zéro import Airflow/DB** | pandas |
| `models/classifier.py` | profils demandeurs | scikit-learn |
| `models/forecaster.py` | prévision de volume | Prophet |
| `models/sla_risk.py` | risque SLA | XGBoost |
| `models/clusterer.py` | NLP et clustering | spaCy, sentence-transformers, scikit-learn |
| `recommender.py` | moteur de règles | PyYAML |
| `rules.yaml` | seuils éditables sans code | — |
| `registry.py` | MLflow (imports **paresseux**) | MLflow |
| `load.py` | upsert des résultats | SQLAlchemy |
| `schema.sql` / `migrate.py` | DDL et bootstrap | — |
| `dags/ml_inference_dag.py` | inférence horaire | Airflow |
| `dags/ml_retrain_dag.py` | réentraînement hebdomadaire | Airflow |

**Principe de conception vérifié dans le code** : `features.py` et tous les `models/*.py`
n'importent jamais Airflow ; toutes les dépendances lourdes sont importées **à l'intérieur des
fonctions** (par exemple `from sklearn.ensemble import RandomForestClassifier` au milieu de
`train()`). Les tâches du DAG ne sont que de fines enveloppes. Cela permet d'exécuter la
majorité des 33 tests de la couche sans installer Prophet, XGBoost ni torch.

### 8.4 Configuration

`Source : ml_engine/config.py`

`MLConfig` (dataclass gelée) expose : `postgres_url`, `tracking_uri`, `artifact_root`,
`model_cache_dir`, `embedding_model`, `spacy_model`, `cold_start_min_rows`, `random_state`,
`top_n_categories` (10), `forecast_horizon_hours` (72), `sla_horizon_hours` (48),
`kmeans_k` (10), `dbscan_eps` (0.5), `dbscan_min_samples` (5),
`experiment_name` (`glpi_ml_engine`), `registry_stage` (`Production`).

Valeurs par défaut notables : `RANDOM_STATE = 42` (fixé partout où c'est supporté),
`COLD_START_MIN_ROWS = 100`, modèle d'embeddings `paraphrase-multilingual-MiniLM-L12-v2`,
modèle spaCy `fr_core_news_sm`.

**Subtilité d'hydratation Airflow** : contrairement au Layer 2, `_hydrate_from_airflow()` ne
déclenche **pas** un import d'Airflow — il n'agit que si `"airflow" in sys.modules`. Le
commentaire du code en donne la raison : un import partiel d'Airflow laisse son ORM SQLAlchemy
à moitié enregistré, ce qui casse ensuite le store SQLite de MLflow (`configure_mappers()`
échoue).

### 8.5 L'ingénierie de variables

`Source : ml_engine/features.py`

**`build_user_features(tickets)`** — une ligne par demandeur (`user_requester`), indexée par
`user_id`, avec 9 variables :

| Variable | Calcul |
| --- | --- |
| `total_tickets` | nombre de tickets |
| `incidents_count` | `type == 1` |
| `requests_count` | `type == 2` |
| `resolved_count` | `status ∈ {5, 6}` |
| `open_count` | complément |
| `high_priority_count` | `priority ∈ {5, 6}` |
| `repetitive_count` | somme des occurrences des `name_normalized` vus ≥ 3 fois |
| `avg_resolution_days` | moyenne de `resolution_days` sur les résolus |
| `tickets_per_month` | `total / max(amplitude_jours / 30, 1)` |

**`build_daily_category_counts(tickets, top_n)`** — pour les `top_n` catégories les plus
volumineuses, un DataFrame `[ds, y]` de comptes journaliers (rééchantillonnage `resample("D")`),
aux noms de colonnes attendus par Prophet.

**`build_sla_features(tickets)`** — une ligne par technicien (`user_assign`) :
`current_open_tickets`, `tickets_last_7_days`, `avg_resolution_days_last_30_days`,
`high_priority_ratio`, `historical_sla_pct`, plus l'étiquette `sla_violation`.

La règle de violation (`_sla_violation_flag`) est explicite : un ticket est en violation si
(résolu **après** son échéance `time_to_resolve`) **ou** (non résolu alors qu'une échéance
existe).

**`build_text_corpus(tickets)`** — `[id, itilcategories_id, date, text]` où
`text = name + ". " + content`, filtré à ≥ 3 caractères.

*Limite documentée dans le code lui-même* : « follow-up content is not persisted by layer 2
yet ». Le Layer 2 extrait bien les suivis (`extract_ticket_followups`) mais ne les persiste
pas — le DAG n'en conserve que le compte (`followup_count`). Le NLP tourne donc sur `name` +
`content` uniquement. Une amorce est prévue dans la fonction pour intégrer une future table
`dim_followups`.

**`dataframe_hash(df)`** — empreinte SHA-256 stable du contenu, journalisée dans MLflow pour la
reproductibilité des entraînements.

### 8.6 Modèle 1 — Classification des demandeurs

`Source : ml_engine/models/classifier.py` — `REGISTERED_MODEL_NAME = "glpi_user_classifier"`

**Problème** : aucune donnée étiquetée à la main n'existe. La solution retenue est un
**amorçage par règles** : un étiqueteur documenté produit les étiquettes, puis un RandomForest
apprend à les reproduire et à généraliser. Le modèle enregistré et servi est la forêt ; les
règles ne sont que le signal d'entraînement.

**Règles (`rule_label`, première correspondance gagnante)** :

| Ordre | Profil | Condition |
| --- | --- | --- |
| 1 | `critique` | `high_ratio ≥ 0.30` **ou** (`high ≥ 3` **et** `avg_res ≥ 5` jours) |
| 2 | `dependant` | `per_month ≥ 4` **ou** `repetitive ≥ 5` **ou** `total ≥ 20` |
| 3 | `autonome` | `total ≤ 5` **et** `resolved_ratio ≥ 0.8` **et** `high == 0` |
| 4 | `standard` | par défaut |

**Modèle** : `RandomForestClassifier(n_estimators=200, max_depth=None,
class_weight="balanced", random_state=42, n_jobs=-1)`.

**Sortie de `predict`** : `[user_id, profile, confidence, features_snapshot]`, où `confidence`
est le maximum de `predict_proba` arrondi à 4 décimales et `features_snapshot` un dictionnaire
des 9 variables (stocké en JSONB, réutilisé plus tard par le moteur de règles).

**Évaluation** : `accuracy`, `f1_macro`, `n_users` — mesurés contre les étiquettes de règles,
c'est-à-dire la cohérence du modèle avec sa source de vérité.

**Démarrage à froid** : si `len(df) < cold_start_min_rows` (100), `train()` renvoie `None` et
journalise un avertissement.

**Interface en ligne de commande** : `python -m ml_engine.models.classifier --train --register`.

### 8.7 Modèle 2 — Prévision de volume

`Source : ml_engine/models/forecaster.py` — `REGISTERED_MODEL_NAME = "glpi_volume_forecaster"`

Le « modèle » est ici un **dictionnaire `{category_id: modèle}`**, un modèle par catégorie du
top-N.

**Prophet** est utilisé si la série compte au moins `MIN_POINTS_FOR_PROPHET = 14` points
journaliers, avec `daily_seasonality=False`, `weekly_seasonality=True`,
`yearly_seasonality=False`, `interval_width=0.8`. L'attribut `confidence = "high"` est posé sur
le modèle.

**Repli `_AverageFallback`** : déclenché si la série est trop courte **ou** si Prophet n'est pas
installé. Il calcule la moyenne et l'écart-type des 14 derniers points et projette
`yhat = moyenne`, `yhat_lower = max(moyenne − 1,96 σ, 0)`, `yhat_upper = moyenne + 1,96 σ`, avec
`confidence = "low"`.

**Horizon** : `forecast_horizon_hours // 24` = **3 points journaliers** (72 h). Les prévisions
négatives sont ramenées à 0 (`clip(lower=0.0)`).

**Sortie** : `[category_id, forecast_date, predicted_count, lower_bound, upper_bound,
confidence]`.

**Évaluation** : rétro-test — pour chaque série suffisamment longue, entraînement sur
`série[:-3]`, prédiction, comparaison à `série[-3:]` ; métriques `rmse`, `mape`,
`n_categories`. Le calcul du `mape` protège la division par zéro
(`denom = where(y_true == 0, 1, y_true)`).

### 8.8 Modèle 3 — Risque de violation du SLA

`Source : ml_engine/models/sla_risk.py` — `REGISTERED_MODEL_NAME = "glpi_sla_risk"`

**Modèle** : `XGBClassifier(n_estimators=150, max_depth=4, learning_rate=0.1, subsample=0.9,
colsample_bytree=0.9, eval_metric="logloss", random_state=42, n_jobs=-1)`.

**Repli statistique** : si le jeu ne contient qu'une seule classe (`len(np.unique(y)) < 2`) ou
moins de 5 techniciens, `SLARiskModel` est construit avec `estimator=None` et
`fallback_rate = y.mean()`. `predict` renvoie alors le taux de base pour tous les techniciens,
avec `confidence = "low"`.

**Sortie** : `[technician_id, risk_score, next_48h_prediction, confidence]`, où
`next_48h_prediction = (risk_score ≥ 0.5)` converti en entier.

**Évaluation** : `accuracy`, `f1`, `auc` (0.0 si une seule classe est présente), `n_techs`.

### 8.9 Modèle 4 — NLP et détection de causes racines

`Source : ml_engine/models/clusterer.py` — `REGISTERED_MODEL_NAME = "glpi_clusterer"`

Chaîne de traitement en cinq étapes :

1. **Prétraitement** — spaCy `fr_core_news_sm` avec `disable=["parser","ner"]`, lemmatisation,
   suppression des mots vides, de la ponctuation, des espaces et des lemmes de moins de
   3 caractères. *Repli* : tokeniseur par expression régulière
   `[a-zàâäéèêëïîôöùûüç]{3,}` plus une liste de mots vides français de base, si spaCy ou le
   modèle est indisponible.
2. **Vectorisation** — `sentence-transformers` avec `paraphrase-multilingual-MiniLM-L12-v2`,
   `normalize_embeddings=True`. *Repli* : `TfidfVectorizer(max_features=512)` avec
   normalisation L2 (afin que la distance euclidienne approche le cosinus, cohérent avec le
   paramètre `eps` de DBSCAN). Le backend effectivement utilisé est retourné et journalisé.
3. **Clustering** — `DBSCAN(eps=0.5, min_samples=5, metric="euclidean")` par défaut, ou
   `KMeans(n_clusters=min(kmeans_k, max(2, n)), n_init=10)` en mode `kmeans`.
4. **Synthèse par cluster** — 5 titres représentatifs tronqués à 120 caractères,
   `ticket_count`, 10 mots-clés par TF-IDF moyen (`top_keywords`), `first_seen` / `last_seen`,
   et une sévérité déduite du volume.
5. **Sentiment** — classifieur lexical léger : deux lexiques français
   (`_NEG_WORDS` : bloqué, impossible, urgent, panne, erreur, plante, cassé, inacceptable,
   lent, problème, critique, mécontent, frustré, colère, catastrophe… ;
   `_POS_WORDS` : merci, parfait, résolu, super, excellent, rapide, content, satisfait,
   génial, top…). La proportion de textes négatifs par cluster donne `neg_ratio`.

**Seuils de sévérité** (`SEVERITY_THRESHOLDS`) : ≥ 100 → `CRITIQUE`, ≥ 50 → `ÉLEVÉ`,
≥ 20 → `MODÉRÉ`, sinon `FAIBLE`.

**Nature transductive** : DBSCAN et K-Means n'offrent pas de méthode `predict` sur de nouvelles
données ; `predict()` résume donc le corpus déjà ajusté. Le bruit DBSCAN (`label == -1`) est
exclu des clusters restitués.

**Évaluation** : `silhouette` (calculée hors bruit, uniquement si ≥ 2 clusters et ≥ 3 points),
`n_clusters`, `noise_ratio`.

### 8.10 Le moteur de recommandations

`Source : ml_engine/recommender.py` + `ml_engine/rules.yaml`

Module « pur » : aucun import Airflow ni base de données. Il reçoit les DataFrames déjà calculés
et le DataFrame des tickets bruts, ce qui le rend entièrement testable (8 tests dédiés).

**Identifiant déterministe** : `_reco_id(type, user, group, cat)` = SHA-1 tronqué à
20 caractères de la chaîne `"type|user|group|cat"`. Conséquence directe : réexécuter
l'inférence **met à jour** la recommandation existante au lieu d'en créer un doublon, grâce au
`ON CONFLICT (id)` du chargeur.

**Les quatre règles** (seuils tirés de `rules.yaml`, `expires_days: 14`) :

| Règle | Type | Sévérité | Condition |
| --- | --- | --- | --- |
| `formation` | `FORMATION` | `ÉLEVÉ` | Utilisateur de profil `critique` dont ≥ **80 %** des incidents portent sur ses **2** premières catégories |
| `automatisation` | `AUTOMATISATION` | `MODÉRÉ` | `repetitive_count > 30` dans le `features_snapshot` du profil |
| `surcharge` | `SURCHARGE` | `CRITIQUE` | Pic prévu > **1,5 ×** la moyenne prévue de la catégorie **et** SLA équipe < **90 %** |
| `cause_racine` | `CAUSE_RACINE` | `CRITIQUE` | Cluster DBSCAN de ≥ **100** tickets, vu au cours des **30** derniers jours |

**SLA d'équipe** : moyenne de `historical_sla_pct` sur les techniciens si le DataFrame
`sla_risk` est disponible ; sinon repli sur `_global_sla_pct(tickets)`, qui calcule directement
la part des tickets résolus dans les délais.

**`evidence_to_json()`** sérialise la colonne `evidence` en JSON avec `ensure_ascii=False`,
donc les accents français sont préservés avant le chargement en JSONB.

Tous les libellés de recommandation sont rédigés **en français** dans le code :
« Formation ciblée pour l'utilisateur … », « Surcharge prévue sur la catégorie … »,
« Cause racine détectée (cluster …) », « Automatiser les demandes répétitives … ».

### 8.11 Le registre MLflow

`Source : ml_engine/registry.py`

Tous les imports MLflow sont **paresseux** (fonction interne `_mlflow()`), afin que l'import du
module n'exige pas que MLflow soit installé.

| Fonction | Rôle |
| --- | --- |
| `configure()` | Fixe l'URI de suivi, crée l'expérience `glpi_ml_engine` avec un emplacement d'artefacts explicite |
| `log_run()` | Journalise paramètres, métriques, empreinte du DataFrame (`input_df_hash`), schéma de variables (`feature_schema`), puis enregistre une nouvelle version |
| `promote_to_production()` | `transition_model_version_stage(..., stage="Production", archive_existing_versions=True)` |
| `load_production_model()` | Charge `models:/<nom>/Production` ; renvoie `None` en cas d'échec, pour permettre un repli **au lieu d'une erreur** |
| `get_production_metrics()` | Métriques de la version en Production, utilisées pour décider d'une promotion |

**`_artifact_uri()`** normalise une racine d'artefacts de façon multiplateforme : les valeurs
portant déjà un schéma (`file:`, `s3://`) et les chemins relatifs sont laissés tels quels ; un
chemin absolu (y compris `C:\...` sous Windows) est converti en URI `file://` via
`Path.as_uri()`, sans quoi la lettre de lecteur serait interprétée comme un schéma d'URI.

**Choix documenté** : MLflow est adossé à **SQLite** et non à un simple store fichier, car un
store `file:./mlruns` ne peut pas enregistrer de modèles ni gérer les stades. MLflow est épinglé
`>=2.12,<3` car la version 3.x exige SQLAlchemy 2.0, incompatible avec Airflow 2.9.3
(SQLAlchemy 1.4). `Source : requirements.txt` (commentaire), `Dockerfile.airflow`

### 8.12 Le DAG d'inférence `ml_inference`

`Source : ml_engine/dags/ml_inference_dag.py`

| Paramètre | Valeur |
| --- | --- |
| `schedule` | `0 * * * *` (horaire) |
| `max_active_runs` | 1 |
| `max_active_tasks` | **1** |
| `retries` / `retry_delay` | 1 / 5 minutes |
| `tags` | `["glpi", "ml", "layer3"]` |

**Pourquoi `max_active_tasks=1`** : les quatre tâches de modèles sont chacune très gourmandes en
mémoire (Prophet, sentence-transformers, spaCy, XGBoost) et chacune relit l'intégralité de la
table des tickets. Les paralléliser dépasserait la mémoire d'une petite machine virtuelle Docker
et provoquerait un arrêt par le tueur OOM. La concurrence Celery est également limitée à 1
(`AIRFLOW__CELERY__WORKER_CONCURRENCY: "1"` dans `docker-compose.yml`).

```mermaid
flowchart TD
    A["check_data_freshness_task<br/>count_recent_tickets(24h)"]
    B["classify_users_task"]
    C["forecast_volume_task"]
    D["predict_sla_risk_task"]
    E["cluster_tickets_task"]
    F["generate_recommendations_task"]
    G["load_ml_results_task"]
    A --> B
    A --> C
    A --> D
    A --> E
    B --> F
    C --> F
    D --> F
    E --> F
    F --> G
```

**Stratégie de chargement des modèles** : pour le classifieur et le risque SLA, la tâche tente
d'abord `registry.load_production_model(...)` ; si rien n'est enregistré, elle **entraîne à la
volée**. Le prévisionniste et le clusteriseur, eux, sont toujours réajustés — leur nature
transductive ou par-catégorie l'impose.

**Contrôle de fraîcheur** : `count_recent_tickets(hours=24)` compte les lignes dont `date_mod`
est dans les 24 dernières heures. Si le compte est nul, un avertissement est émis mais le DAG
**continue** sur la table complète : le contrôle est informatif, pas bloquant.

### 8.13 Le DAG de réentraînement `ml_retrain`

`Source : ml_engine/dags/ml_retrain_dag.py`

| Paramètre | Valeur |
| --- | --- |
| `schedule` | `0 2 * * 0` (dimanche 02 h 00) |
| `tags` | `["glpi", "ml", "layer3", "retrain"]` |

Une seule tâche, **dynamiquement dépliée** avec `.expand(model_key=[...])` sur les 4 modèles.

`MODEL_SPECS` définit pour chacun la métrique principale et son sens d'amélioration :

| Modèle | Module | Saveur MLflow | Métrique | Plus haut = mieux |
| --- | --- | --- | --- | --- |
| `classifier` | `ml_engine.models.classifier` | `sklearn` | `f1_macro` | oui |
| `sla_risk` | `ml_engine.models.sla_risk` | `xgboost` | `f1` | oui |
| `forecaster` | `ml_engine.models.forecaster` | `sklearn` | `mape` | **non** |
| `clusterer` | `ml_engine.models.clusterer` | `sklearn` | `silhouette` | oui |

**Promotion conditionnelle** : la nouvelle version n'est promue en `Production` que si sa
métrique s'améliore par rapport à la version actuellement en Production, ou si aucune version
n'existe encore. En cas de démarrage à froid, la tâche renvoie
`{"promoted": False, "reason": "cold_start"}`.

`estimator = getattr(model, "estimator", model)` permet de dégrouper les modèles encapsulés dans
des dataclasses (`ClassifierModel`, `SLARiskModel`) avant journalisation.

### 8.14 Le schéma des résultats ML

`Source : ml_engine/schema.sql`

| Table | Clé primaire | Colonnes notables |
| --- | --- | --- |
| `ml_user_profiles` | `user_id` | `profile`, `confidence`, `features_snapshot` **JSONB**, `computed_at` |
| `ml_forecasts` | `(category_id, forecast_date)` | `predicted_count`, `lower_bound`, `upper_bound`, `confidence`, `model_version` |
| `ml_sla_risk` | `technician_id` | `risk_score`, `next_48h_prediction`, `confidence`, `model_version` |
| `ml_clusters` | `(algorithm, cluster_id)` | `sample_titles` **JSONB**, `ticket_count`, `top_keywords` **JSONB**, `severity`, `neg_ratio`, `first_seen`, `last_seen` |
| `recommendations` | `id` (TEXT, hachage) | `type`, `target_user_id`, `target_group_id`, `target_category_id`, `severity`, `title`, `description`, `evidence` **JSONB**, `created_at`, `expires_at` |

Index : `idx_reco_type`, `idx_reco_user`, `idx_forecast_date`, `idx_clusters_sev`.

**Chargement** (`Source : ml_engine/load.py`) : même motif de staging qu'au Layer 2, avec en
plus un transtypage explicite `CAST(col AS JSONB)` dans le `SELECT` de l'insertion, pour que
psycopg2 stocke un véritable JSONB et non du texte. Les tables `ml_*` reçoivent en outre
`computed_at = NOW()` lors d'un conflit ; `recommendations` non, car elle porte `created_at`.

### 8.15 Entrées / Sorties

| | Entrée | Sortie |
| --- | --- | --- |
| **Données** | `SELECT * FROM dim_tickets_enriched` | 5 tables `ml_*` / `recommendations` |
| **Modèles** | Registre MLflow (stade `Production`) | Nouvelles versions enregistrées, promotion conditionnelle |
| **Configuration** | `POSTGRES_URL`, `MLFLOW_TRACKING_URI`, `MLFLOW_ARTIFACT_ROOT`, variables `ML_*` | — |
| **Règles métier** | `ml_engine/rules.yaml` | — |

### 8.16 Gestion des erreurs

La stratégie dominante de la couche est la **dégradation gracieuse plutôt que l'échec** :

| Situation | Comportement |
| --- | --- |
| Moins de 100 tickets | `train()` renvoie `None`, la tâche renvoie une liste vide |
| Prophet absent ou série trop courte | `_AverageFallback` avec `confidence="low"` |
| Classe unique / moins de 5 techniciens | Taux historique, `confidence="low"` |
| spaCy indisponible | Tokeniseur par expression régulière |
| sentence-transformers indisponible | Vecteurs TF-IDF |
| Aucun modèle en Production | Entraînement à la volée dans la tâche d'inférence |
| Corpus textuel vide | `train()` renvoie `None` |
| Moins de 2 clusters | `silhouette = 0.0`, sans exception |

`load_production_model` intercepte toute exception et renvoie `None`, avec journalisation en
`WARNING` — jamais d'interruption du DAG pour un modèle manquant.


---

## 9. Layer 4 — `api/` — Backend FastAPI (REST + WebSocket)

### 9.1 Objectif

Servir en lecture les données de l'entrepôt (Layer 2) et les résultats ML (Layer 3) sous forme
d'API REST JSON et de flux WebSocket temps réel, avec authentification JWT, contrôle d'accès par
rôle, cache Redis, limitation de débit, journalisation structurée et métriques Prometheus.

**Règle d'écriture** : cette couche **n'écrit jamais** dans les tables des Layers 2 et 3. Elle
possède exactement deux tables : `api_users` et `recommendation_acks`.
`Source : api/migrations/api_users_and_acks.sql`, `api/queries/recommendations.py`

### 9.2 Architecture

```mermaid
flowchart TD
    REQ["Requête HTTP<br/>Angular"]
    CORS["CORSMiddleware<br/>(enregistré EN DERNIER<br/>= le plus externe)"]
    CTX["context_middleware<br/>X-Request-ID, durée,<br/>capture des exceptions"]
    SLOW["SlowAPIMiddleware<br/>limitation de débit"]
    RTR["Routeur<br/>+ Depends(require_role)"]
    CACHE{"Cache Redis ?"}
    QRY["queries/*.py<br/>SQL texte"]
    PG[("PostgreSQL glpi_dw<br/>asyncpg")]
    SCH["schemas/*.py<br/>Pydantic v2"]
    RESP["Réponse JSON"]

    REQ --> CORS --> CTX --> SLOW --> RTR
    RTR --> CACHE
    CACHE -->|"hit"| SCH
    CACHE -->|"miss"| QRY --> PG --> SCH --> RESP

    BC["alerts/broadcaster.py<br/>tâche de fond, 10 s"]
    WS["WS /ws/alerts"]
    PG -.->|"SELECT recommendations<br/>WHERE severity='CRITIQUE'"| BC --> WS
```

### 9.3 Composants

| Fichier | Rôle |
| --- | --- |
| `main.py` | Fabrique d'application : middlewares, gestionnaires d'erreurs, routeurs, `/metrics`, cycle de vie |
| `config.py` | `Settings` pydantic-settings ; coercition de l'URL PostgreSQL vers asyncpg |
| `database.py` | Moteur async SQLAlchemy 2.x + dépendance `get_session` |
| `security.py` | JWT (création / vérification), bcrypt, `require_role(...)` |
| `cache.py` | Cache Redis asynchrone à deux paliers |
| `logging_config.py` | Journalisation JSON avec corrélation par `request_id` |
| `routers/` | 13 modules : auth, overview, 6 onglets, predictions, recommendations, websocket, health |
| `schemas/` | Modèles Pydantic v2 : `common`, `auth`, `overview`, `tabs` |
| `queries/` | Constructeurs SQL : `shared`, `overview`, `tabs`, `predictions`, `recommendations` |
| `alerts/broadcaster.py` | Sondeur en tâche de fond + diffusion WebSocket |
| `migrations/` | `api_users_and_acks.sql` + `seed_users.py` |
| `schema_indexes.sql` | Index de performance optionnels sur `dim_tickets_enriched` |
| `tests/` | 42 tests pytest (base de données simulée, JWT réel) |

### 9.4 Configuration

`Source : api/config.py`

`Settings` (pydantic-settings, `env_file=".env"`, `extra="ignore"`) :

| Champ | Alias d'environnement | Défaut |
| --- | --- | --- |
| `postgres_url` | `POSTGRES_URL` | `postgresql+psycopg2://glpi:glpi@postgres:5432/glpi_dw` |
| `db_pool_size` | `API_DB_POOL_SIZE` | 5 |
| `db_max_overflow` | `API_DB_MAX_OVERFLOW` | 10 |
| `redis_url` | `REDIS_URL` | `redis://redis:6379/0` |
| `cache_ttl_overview` | `API_CACHE_TTL_OVERVIEW` | 60 s |
| `cache_ttl_heavy` | `API_CACHE_TTL_HEAVY` | 300 s |
| `jwt_secret` | `API_JWT_SECRET` | `change-me-in-prod` |
| `jwt_algorithm` | `API_JWT_ALGORITHM` | `HS256` |
| `access_token_ttl_min` | `API_ACCESS_TOKEN_TTL_MIN` | 30 min |
| `refresh_token_ttl_days` | `API_REFRESH_TOKEN_TTL_DAYS` | 7 j |
| `allowed_origins` | `API_ALLOWED_ORIGINS` | `http://localhost:4200` |
| `rate_limit_anon` | `API_RATE_LIMIT_ANON` | `100/minute` |
| `rate_limit_auth` | `API_RATE_LIMIT_AUTH` | `300/minute` |
| `alert_poll_seconds` | `API_ALERT_POLL_SECONDS` | 10 s |

**Coercition automatique du pilote** : le validateur `_to_asyncpg` convertit
`postgresql+psycopg2://`, `postgresql://` ou `postgres://` en `postgresql+asyncpg://`. La même
variable `POSTGRES_URL` sert donc aux Layers 2, 3 et 4 sans duplication de configuration.

`get_settings()` est décoré par `@lru_cache` : les réglages sont lus une seule fois.

### 9.5 Les 20 points d'entrée exposés

`Source : api/routers/*.py`

| Méthode | Chemin | Rôles autorisés | Cache | Tables lues |
| --- | --- | --- | --- | --- |
| `POST` | `/api/auth/login` | public | — | `api_users` |
| `POST` | `/api/auth/refresh` | public (jeton de rafraîchissement) | — | — |
| `GET` | `/api/auth/me` | authentifié | — | `api_users` |
| `GET` | `/api/overview` | DSI, MANAGER, DIRECTION | **60 s** | `dim_tickets_enriched`, `dim_entities`, `dim_categories`, `dim_users`, `ml_clusters`, `recommendations` |
| `GET` | `/api/demandeurs` | les 3 rôles | — | `dim_tickets_enriched`, `dim_users`, `ml_user_profiles` |
| `GET` | `/api/services` | les 3 rôles | — | `dim_tickets_enriched`, `dim_groups` |
| `GET` | `/api/sites` | les 3 rôles | **300 s** | `dim_tickets_enriched`, `dim_entities` |
| `GET` | `/api/repetitifs` | les 3 rôles | — | `ml_clusters` |
| `GET` | `/api/techniciens` | les 3 rôles | **300 s** | `dim_tickets_enriched`, `dim_users`, `ml_sla_risk` |
| `GET` | `/api/categories` | les 3 rôles | — | `dim_tickets_enriched`, `dim_categories` |
| `GET` | `/api/predictions/volume` | les 3 rôles | — | `ml_forecasts`, `dim_categories` |
| `GET` | `/api/predictions/sla_risk` | les 3 rôles | — | `ml_sla_risk`, `dim_users` |
| `GET` | `/api/recommendations` | les 3 rôles | — | `recommendations`, `recommendation_acks` |
| `POST` | `/api/recommendations/{id}/acknowledge` | **DSI, MANAGER uniquement** | invalide le cache `overview` | `recommendation_acks` (écriture) |
| `WS` | `/ws/alerts` | jeton d'accès en paramètre d'URL | — | `recommendations` |
| `GET` | `/health` | public | — | — |
| `GET` | `/health/db` | public | — | `SELECT 1` |
| `GET` | `/metrics` | public | — | — |
| `GET` | `/docs`, `/redoc` | public | — | — |

**Filtres communs** — `CommonFilters` (`Source : api/schemas/common.py`) : `start_date`,
`end_date`, `limit` (1 à 500, défaut 50), `entity_id`, `category_id`. Exposés en paramètres de
requête via la dépendance `common_filters`, donc automatiquement documentés dans OpenAPI.

### 9.6 La construction du SQL

`Source : api/queries/shared.py`

Trois éléments partagés encodent les conventions métier :

```
SLA_MET_EXPR = (solvedate IS NOT NULL
                AND (time_to_resolve IS NULL OR solvedate <= time_to_resolve))
IS_OPEN_EXPR = (is_resolved IS NOT TRUE)
```

`ticket_filters(f, prefix)` produit un fragment `WHERE` joint par `AND` et le dictionnaire de
paramètres liés. Il accepte un préfixe d'alias de table (`"t."`). La borne haute de date est
inclusive sur la journée : `date < (:end_date::date + INTERVAL '1 day')`.

**`user_name_expr(id_col)`** — expression d'affichage du nom d'un utilisateur, avec un point
d'attention explicitement documenté dans le code :

```sql
COALESCE(
  NULLIF(TRIM(COALESCE(u.realname,'')||' '||COALESCE(u.firstname,'')), ''),
  u.name,
  'user #'||<colonne_côté_faits>::text,
  'Inconnu')
```

Le repli final doit utiliser la colonne **côté faits** (`t.user_assign`) et non `u.id` : sur un
échec de jointure `LEFT JOIN`, toutes les colonnes `u.*` valent `NULL`, donc un repli `u.id`
produirait `NULL` et ferait échouer le champ Pydantic non optionnel `name` — soit une erreur 500
sur l'ensemble du point d'entrée.

**Deux pièges SQL documentés dans le code** :
1. `'x #'||NULL` vaut `NULL` en SQL. Un libellé construit par concaténation avec un identifiant
   nullable produit `NULL`, pas le préfixe. Tout `COALESCE` doit donc se terminer par une
   **littérale** (`'Sans catégorie'`, `'Sans site'`, `'Inconnu'`).
2. asyncpg est strict sur les types de paramètres : il infère `$1` dans
   `(:horizon || ' days')::interval` comme du texte et rejette un entier. Le code utilise donc
   `make_interval(days => :horizon)`. `Source : api/queries/predictions.py`

**Exclusion de l'entité racine** : `entities_id = 0` est la « Root entity » de GLPI, parent par
défaut de toute entité et non un site réel. Elle est exclue du classement **et** du total servant
au calcul de `part_pct`. `Source : api/queries/tabs.py::get_sites`

**Criticité d'un service** — dérivée du ratio de tickets à haute priorité
(`Source : api/queries/tabs.py::_criticality`) : ≥ 0,5 → `CRITIQUE` ; ≥ 0,25 → `ÉLEVÉ` ;
≥ 0,1 → `MODÉRÉ` ; sinon `FAIBLE`.

### 9.7 Le point d'entrée `/api/overview`

`Source : api/queries/overview.py` — le plus riche : **six requêtes SQL** pour une réponse.

1. **Agrégats KPI en une passe** : `total`, `resolved_pct`, `sla_pct`, `active_sites`.
2. **Tickets répétitifs** : `SUM(ticket_count)` sur `ml_clusters`.
3. **Top 10 des sites** : jointure `dim_entities`, entité 0 exclue.
4. **Top 8 des catégories** (graphique en anneau) : jointure `dim_categories`.
5. **Top 10 des demandeurs** : jointure `dim_users`, via `user_name_expr`.
6. **SLA par technicien** (15 premiers) : moyenne de `SLA_MET_EXPR`.
7. **Top 4 des alertes ML** : `recommendations` non expirées, triées par sévérité
   (`CRITIQUE` → `ÉLEVÉ` → `MODÉRÉ` → autre) puis par date décroissante.

Réponse : `OverviewResponse{kpis, charts, alerts}` (`Source : api/schemas/overview.py`).

### 9.8 Sécurité

`Source : api/security.py`

**Jetons JWT** — algorithme `HS256` via `python-jose`. Charge utile :
`{sub: nom d'utilisateur, role, type: "access"|"refresh", iat, exp}`.
Durées : accès 30 minutes, rafraîchissement 7 jours.

**Mots de passe** — `passlib` avec `bcrypt` (`CryptContext(schemes=["bcrypt"])`). Aucun mot de
passe en clair n'est stocké : `api_users.password_hash` contient l'empreinte bcrypt.

**Chaîne d'authentification** :
1. `OAuth2PasswordBearer(tokenUrl="/api/auth/login")` extrait le jeton porteur.
2. `decode_token()` le vérifie ; un `JWTError` devient un `401`.
3. `get_current_user()` refuse un jeton de type autre que `"access"`, refuse un `sub` absent, et
   **revérifie l'existence de l'utilisateur en base** — un jeton valide dont l'utilisateur a été
   supprimé est rejeté (`401 "User no longer exists"`).
4. `require_role(*allowed)` renvoie une dépendance produisant un `403` si le rôle ne figure pas
   dans la liste autorisée.

**Trois rôles** : `DSI`, `MANAGER`, `DIRECTION`, contraints au niveau du schéma SQL
(`CHECK (role IN ('DSI','MANAGER','DIRECTION'))`).
**Matrice d'accès** : les trois rôles lisent tout ; seuls `DSI` et `MANAGER` peuvent acquitter
une recommandation (`_WRITE = require_role("DSI", "MANAGER")`).

**Authentification WebSocket** : les navigateurs ne peuvent pas fixer d'en-tête `Authorization`
sur une connexion WebSocket ; le jeton d'accès passe donc en paramètre d'URL
(`ws://host/ws/alerts?token=<jeton>`). Le jeton est décodé et son type vérifié ; en cas d'échec,
la connexion est fermée avec le code `1008 POLICY_VIOLATION` **avant** l'acceptation.
`Source : api/routers/websocket.py`

**Limitation de débit** — `slowapi`. La clé de comptage est le jeton porteur pour un appelant
authentifié, sinon l'adresse IP du client : chaque utilisateur et chaque IP anonyme dispose donc
de son propre seau. `Source : api/main.py::_key_func`

**Utilisateurs de démonstration** — `api/migrations/seed_users.py` insère trois comptes par
`INSERT … ON CONFLICT (username) DO UPDATE`, avec des mots de passe explicitement marqués
« DEV DEFAULTS ONLY » dans le code : `dsi@sartex`, `manager@sartex`, `direction@sartex`.

### 9.9 Ordre des middlewares — un point d'architecture critique

`Source : api/main.py` (commentaire de 6 lignes dans le code)

Starlette encapsule les middlewares **dans l'ordre inverse de leur enregistrement**. Le
`CORSMiddleware` est donc enregistré **en dernier** afin d'être la couche la **plus externe**.

Si CORS était enregistré avant le `context_middleware` qui capture les exceptions, la réponse
500 synthétisée par ce dernier échapperait à CORS et arriverait au navigateur **sans** en-tête
`Access-Control-Allow-Origin`. Le navigateur bloquerait alors la réponse et le frontend ne
pourrait signaler qu'un opaque « 0 Unknown Error » au lieu du vrai code de statut.

### 9.10 Gestion des erreurs

**Enveloppe unique** — toute erreur renvoie
`{"error": {"code": ..., "message": ..., "details": {...}}}`. Aucune trace de pile n'est
divulguée. `Source : api/main.py::_error`

| Gestionnaire | Déclencheur | Code renvoyé |
| --- | --- | --- |
| `http_exc_handler` | `StarletteHTTPException` | code d'origine, `code = "http_<n>"` |
| `validation_handler` | `RequestValidationError` | `422`, `validation_error`, détail des erreurs |
| `ratelimit_handler` | `RateLimitExceeded` | `429`, `rate_limited` |
| `unhandled_handler` | toute `Exception` | `500`, `internal_error` |
| `context_middleware` | exception pendant `call_next` | `500` + en-tête `X-Request-ID` |

**Dégradation du cache** : toutes les opérations Redis sont enveloppées dans un `try/except` qui
journalise en `WARNING` et poursuit. Une panne de Redis dégrade l'API en « toujours manquant »,
jamais en erreur 500. `Source : api/cache.py`

**`/health/db`** renvoie `503` avec `{"status":"error","db":"unreachable"}` si `SELECT 1` échoue.

### 9.11 Journalisation et observabilité

`Source : api/logging_config.py`

Journalisation **JSON structurée** via un `JsonFormatter` personnalisé. Chaque ligne porte :
`level`, `logger`, `message`, `request_id`, `user`, `route`, plus `duration_ms` et `exc` quand
ils sont disponibles.

La corrélation repose sur trois `ContextVar` (`request_id_var`, `user_var`, `route_var`)
positionnées par le `context_middleware`, si bien que **toute** ligne émise pendant une requête
porte automatiquement son identifiant. Le `X-Request-ID` entrant est réutilisé s'il est fourni,
sinon un `uuid4` est généré ; il est renvoyé dans l'en-tête de réponse.

**Métriques Prometheus** : `Instrumentator().instrument(app).expose(app, endpoint="/metrics")`.

### 9.12 Le diffuseur d'alertes temps réel

`Source : api/alerts/broadcaster.py`

Une unique tâche asyncio de fond, démarrée dans le `lifespan` de l'application, interroge la
table `recommendations` toutes les `alert_poll_seconds` (10 s par défaut).

**Amorçage** : au tout premier passage, `_last_seen` est initialisé à
`COALESCE(MAX(created_at), NOW()::timestamp)` **sans rien diffuser** — l'historique n'est donc
jamais rejoué à la connexion d'un client.

**Ensuite** : `SELECT … WHERE severity = 'CRITIQUE' AND created_at > :since ORDER BY created_at
ASC`, puis diffusion d'un `WsAlert` à tous les clients enregistrés.

**Détails de robustesse observés dans le code** :
- `_as_naive_utc()` retire le fuseau horaire : `recommendations.created_at` est un `TIMESTAMP`
  naïf et asyncpg refuse de lier une date-heure porteuse de fuseau contre une colonne naïve.
- Le `NOW()::timestamp` est explicitement transtypé : `NOW()` seul est `timestamptz` et
  promouvrait tout le `COALESCE` en valeur avec fuseau.
- `broadcast()` collecte les sockets morts pendant l'envoi et les retire de l'ensemble.
- L'ensemble des clients est protégé par un `asyncio.Lock`.
- La boucle intercepte toute exception de sondage en `WARNING` sans s'arrêter.
- L'arrêt utilise un `asyncio.Event` avec `wait_for(timeout=interval)`, ce qui rend l'arrêt
  immédiat plutôt que de devoir attendre la fin de l'intervalle.

**Limite documentée** : l'état est en mémoire du processus. Avec plusieurs workers gunicorn,
chaque worker détient son propre ensemble de clients et son propre repère temporel. Le
docker-compose de développement lance donc **un seul worker uvicorn** ; pour une diffusion
multi-workers en production, le code indique qu'il faut remplacer la livraison par un
publish/subscribe Redis. `Source : docker-compose.yml`, `api/alerts/broadcaster.py`,
`Dockerfile.api`

### 9.13 Entrées / Sorties

| | Entrée | Sortie |
| --- | --- | --- |
| **Données** | Tables `dim_*`, `ml_*`, `recommendations`, `api_users`, `recommendation_acks` | JSON validé par Pydantic v2 |
| **Requêtes** | HTTP GET/POST + paramètres `CommonFilters`, WebSocket | Réponses JSON, trames WebSocket |
| **Sécurité** | En-tête `Authorization: Bearer <jeton>` ; `?token=` en WebSocket | `401`, `403`, `429` selon le cas |
| **Écriture** | `POST /api/recommendations/{id}/acknowledge` | Ligne dans `recommendation_acks` |

---

## 10. Layer 5 — `frontend/` — Tableau de bord Angular

### 10.1 Objectif

Restituer les données du Layer 4 sous forme d'un tableau de bord interactif, thémable et temps
réel. La couche **ne lit que l'API** : elle ne possède aucune base de données et ne communique
jamais directement avec les Layers 1 à 3.

### 10.2 Pile technique

`Source : frontend/package.json`, `frontend/src/app/app.config.ts`

| Élément | Version / bibliothèque | Justification lisible dans le code |
| --- | --- | --- |
| Framework | Angular **17.3**, composants *standalone* (sans NgModule) | routes chargées à la demande |
| État | **Signals Angular** + RxJS | pas de magasin NgRx |
| Graphiques | `chart.js` 4.5 + `ng2-charts` **5.0** | v5 est la ligne compatible Angular 17 ; les `registerables` sont enregistrés une seule fois dans `app.config.ts` |
| Icônes | `lucide-angular` | 30 icônes explicitement importées |
| Polices | `@fontsource/inter`, `@fontsource/jetbrains-mono` | embarquées localement, aucun CDN Google |
| Alertes | `sweetalert2` | encapsulé dans `NotificationService` |
| Dates | `date-fns` | — |
| Composants | `@angular/cdk` | — |
| Tests | Karma + Jasmine | une spécification par composant |

### 10.3 Arborescence applicative

`Source : frontend/src/app/`

```
frontend/src/app/
├── core/
│   ├── services/      api, auth, dashboard, websocket, theme, notification
│   ├── interceptors/  jwt, refresh, error
│   ├── guards/        auth, role
│   └── models/        auth, common, overview, tabs
├── shared/
│   ├── components/    kpi-card, data-table, bar-chart, horiz-bar-chart,
│   │                  donut-chart, scatter-chart, sla-bar, badge,
│   │                  skeleton-loader, theme-toggle, alerts-panel,
│   │                  tab-scaffold, placeholder-page
│   ├── directives/    count-up (nombres animés), stagger (apparition en cascade)
│   ├── animations.ts  fondu de route, fade-up, stagger
│   ├── chart-theme.ts thème des graphiques
│   └── tab-utils.ts   topSeries, stackedSeries, withRank, profileTone
├── layout/            main-layout, auth-layout, sidebar, header, nav.config
├── pages/             dashboard, demandeurs, services, sites, repetitifs,
│                      techniciens, categories, login, settings
├── app.config.ts      fournisseurs : routeur, HttpClient + intercepteurs,
│                      animations, icônes, Chart.js
└── app.routes.ts      routes paresseuses derrière authGuard
```

### 10.4 Routage

`Source : frontend/src/app/app.routes.ts`

Deux branches :

- `/login` → `AuthLayoutComponent` avec `LoginComponent` en enfant (pas de garde).
- `/` → `MainLayoutComponent` protégé par **`authGuard`**, avec 8 enfants tous chargés à la
  demande via `loadComponent` : `dashboard` (redirection par défaut), `demandeurs`, `services`,
  `sites`, `repetitifs`, `techniciens`, `categories`, `settings`.
- `**` → redirection vers `/`.

`settings` porte en outre `roleGuard` avec `data: { roles: [] }`. Comme `roleGuard` renvoie
`true` quand la liste est vide, la route est aujourd'hui ouverte à tous les rôles : le mécanisme
est câblé mais non restreint. `Source : frontend/src/app/core/guards/role.guard.ts`

### 10.5 Les sept onglets analytiques

`Source : frontend/src/app/layout/nav.config.ts`

| Libellé | Route | Icône | Point d'entrée appelé |
| --- | --- | --- | --- |
| Vue d'ensemble | `/dashboard` | `layout-dashboard` | `GET /api/overview` |
| Demandeurs | `/demandeurs` | `users` | `GET /api/demandeurs` |
| Services | `/services` | `building-2` | `GET /api/services` |
| Sites | `/sites` | `map-pin` | `GET /api/sites` |
| Répétitifs | `/repetitifs` | `repeat` | `GET /api/repetitifs` |
| Techniciens | `/techniciens` | `wrench` | `GET /api/techniciens` |
| Catégories | `/categories` | `tags` | `GET /api/categories` |

Plus `Paramètres` (`/settings`) en pied de barre latérale.

### 10.6 La couche de services

**`ApiService`** (`Source : frontend/src/app/core/services/api.service.ts`) — enveloppe fine
d'`HttpClient` qui préfixe `environment.apiBaseUrl` et normalise les paramètres de requête en
supprimant `null`, `undefined` et `''`.

**`AuthService`** (`Source : .../auth.service.ts`) — état exposé par **signals** :
`accessToken`, `role`, `currentUser`, et le calculé `isAuthenticated`. Les jetons sont persistés
dans `localStorage` sous les clés `sartex.access_token`, `sartex.refresh_token`, `sartex.role`.
Méthodes : `login`, `refresh`, `fetchMe`, `logout`, `hasRole`.

**`DashboardService`** (`Source : .../dashboard.service.ts`) — contient la logique
d'**adaptation de format** entre l'API et les modèles du frontend :
- `toOverview()` transforme la réponse `{kpis, charts, alerts}` en six cartes KPI libellées en
  français (« Total tickets », « Résolus », « SLA global », « Tickets répétitifs »,
  « Sites actifs », « Top catégorie ») et en quatre séries de graphiques.
- `remapTab(path, res)` déballe l'enveloppe `{items: [...]}` renvoyée par chaque onglet et
  renomme les champs selon la route (`sla_pct` → `sla_rate`, `service` → `name`,
  `ticket_count` → `count`, etc.).

**`WebsocketService`** (`Source : .../websocket.service.ts`) — se connecte à
`${wsBaseUrl}/ws/alerts?token=<jeton encodé>`. Signals exposés : `unread`, `alerts` (tampon des
50 dernières), `connected`. Reconnexion automatique programmée à **5 secondes** après une
fermeture, uniquement si l'utilisateur est encore authentifié. Chaque alerte reçue peut
déclencher un toast et/ou incrémenter le badge selon les préférences lues dans
`localStorage['sartex.notif.prefs']`.

### 10.7 Les trois intercepteurs HTTP

`Source : frontend/src/app/core/interceptors/`

L'ordre d'enregistrement dans `app.config.ts` est `[jwt, refresh, error]`.

| Intercepteur | Comportement |
| --- | --- |
| `jwtInterceptor` | Ajoute `Authorization: Bearer <jeton>`, **sauf** sur `/api/auth/login` et `/api/auth/refresh` |
| `refreshInterceptor` | Sur un `401` (hors appels d'authentification, et seulement si un jeton de rafraîchissement existe) : tente **un** rafraîchissement puis rejoue la requête. En cas d'échec du rafraîchissement : `logout()` puis redirection vers `/login` |
| `errorInterceptor` | Affiche un toast d'erreur, en restant **silencieux** sur `/api/auth/login` et sur les `401` (déjà traités par l'intercepteur précédent) |

### 10.8 Thème et expérience utilisateur

Deux thèmes de premier plan (clair et sombre). L'ensemble de la palette — l'indigo de marque
Sartex `#27316E` et son échelle, les couleurs sémantiques, les gris chauds — est défini en
**propriétés personnalisées CSS** dans `src/styles.css` ; aucun composant ne code une couleur en
dur. Les graphiques relisent ces variables et se redessinent au changement de thème.
`Source : frontend/src/styles.css`, `frontend/src/app/shared/components/chart-theme.ts`

Autres éléments d'interface vérifiés dans le code : barre latérale repliable dont l'état est
persisté, tableaux triables / filtrables / paginés avec **export CSV**, squelettes de chargement
(`skeleton-loader`), directives `count-up` (nombres animés) et `stagger` (apparition en cascade),
états d'erreur stylés avec bouton de réessai (`tab-scaffold`), fichier de traduction
`src/assets/i18n/fr.json`.

### 10.9 Configuration et déploiement

`Source : frontend/src/environments/environment.ts`

```ts
export const environment = {
  production: false,
  apiBaseUrl: 'http://localhost:8000',
  wsBaseUrl: 'ws://localhost:8000',
};
```

`environment.prod.ts` en contient l'équivalent de production. Aucune autre configuration n'est
nécessaire : thème, état de la barre latérale et jetons sont persistés côté client dans
`localStorage`.

Commandes : `npm start` (= `ng serve`, port 4200), `npm run build`
(sortie `frontend/dist/frontend/browser/`), `npm test` (Karma + Jasmine).
`Source : frontend/package.json`

### 10.10 Entrées / Sorties

| | Entrée | Sortie |
| --- | --- | --- |
| **Données** | JSON du Layer 4, trames WebSocket | Rendu HTML/Canvas : KPI, graphiques, tableaux |
| **Utilisateur** | Identifiants de connexion, filtres, tris, clics d'acquittement | `POST /api/auth/login`, `POST /api/recommendations/{id}/acknowledge` |
| **Persistance locale** | `localStorage` : jetons, rôle, thème, état de la barre latérale, préférences de notification | — |

### 10.11 Gestion des erreurs

- Chaque page expose des signals `loading` / `error` ; en cas d'échec de l'appel, l'onglet
  affiche un état d'erreur stylé avec un bouton de réessai plutôt que de planter.
  `Source : frontend/src/app/pages/*/*.component.ts`, `tab-scaffold.component.ts`
- Les erreurs HTTP inattendues deviennent des toasts (`errorInterceptor`).
- Un `401` déclenche une tentative de rafraîchissement transparente ; son échec provoque la
  déconnexion et le retour à l'écran de connexion.
- Une déconnexion WebSocket programme une reconnexion à 5 secondes.
- `remapTab` et `toOverview` utilisent systématiquement `?? []` et `?? 0`, de sorte qu'une
  réponse partielle ne provoque pas d'exception de rendu.


---

## 11. Flux complet des données

### 11.1 Vue synthétique

```mermaid
flowchart TD
    A["<b>GLPI</b><br/>Tickets opérationnels"]
    B["<b>Extraction</b><br/>glpi_connector<br/>/search/Ticket + /{itemtype}"]
    C["<b>Données brutes</b><br/>list[dict] à clés numériques<br/>remappées en noms lisibles"]
    D["<b>Transformation</b><br/>etl/transform.py<br/>pandas"]
    E["<b>Données nettoyées</b><br/>+ 4 colonnes dérivées<br/>+ colonnes _display"]
    F["<b>Résolution des FK</b><br/>etl/load.py<br/>libellés → identifiants"]
    G["<b>Entrepôt</b><br/>dim_tickets_enriched<br/>dim_* + fact_kpis_daily"]
    H["<b>Ingénierie de variables</b><br/>ml_engine/features.py"]
    I["<b>Modèles</b><br/>RandomForest / Prophet<br/>XGBoost / DBSCAN"]
    J["<b>Moteur de règles</b><br/>recommender.py + rules.yaml"]
    K["<b>Résultats ML</b><br/>ml_* + recommendations"]
    L["<b>Service</b><br/>FastAPI + cache Redis"]
    M["<b>Consommation</b><br/>Angular : 7 onglets<br/>+ alertes temps réel"]

    A --> B --> C --> D --> E --> F --> G --> H --> I --> J --> K --> L --> M
    G --> L
    K -.->|"WebSocket"| M
```

### 11.2 Détail étape par étape

| # | Étape | Donnée entrante | Composant récepteur | Traitement | Sortie | Fichier |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Ouverture de session | App-Token + User-Token | `GLPIClient.init_session` | `GET /initSession` | `session_token` | `glpi_connector/client.py` |
| 2 | Recherche paginée | `forcedisplay[]` + `range` | `GLPIClient.search` | Pagination par `len(data)`, réessais | Générateur de lignes brutes | `glpi_connector/client.py` |
| 3 | Remappage | Ligne à clés `"2"`, `"12"`… | `_remap` | Application de `TICKET_FIELD_MAP` | `dict` à clés lisibles | `glpi_connector/extractors.py` |
| 4 | Extraction des dimensions | — | `extract_users/entities/categories/groups` | `GET /{itemtype}` + `expand_dropdowns` + `_slim` | 4 `list[dict]` | `glpi_connector/extractors.py` |
| 5 | Transport vers Celery | `list[dict]` | `transform_task` | `.delay()` via Redis | `AsyncResult` | `etl/dags/glpi_polling_dag.py` |
| 6 | Mise en DataFrame | `list[dict]` | `to_dataframe` | Renommage, suppression des colonnes inconnues | DataFrame à 19 colonnes | `etl/transform.py` |
| 7 | Analyse des dates | Chaînes GLPI | `parse_dates` | `pd.to_datetime(errors="coerce")` | 5 colonnes `datetime64` | `etl/transform.py` |
| 8 | Traitement des FK | `"Root entity > Usine A"` | `coerce_fk_ids` | Aplatissement, sauvegarde en `_display`, `Int64` | 5 colonnes `Int64` (`NA`) + 5 `_display` | `etl/transform.py` |
| 9 | Colonnes dérivées | statut, priorité, dates, titre | `add_derived` | Règles GLPI | `is_resolved`, `is_high_priority`, `resolution_days`, `name_normalized` | `etl/transform.py` |
| 10 | Calcul des KPI | DataFrame | `compute_kpis` | Agrégations | 4 indicateurs | `etl/transform.py` |
| 11 | Chargement des dimensions | 4 `list[dict]` | `load_dimension` | Transtypage + staging + upsert | `dim_users/entities/categories/groups` | `etl/load.py` |
| 12 | Résolution des libellés | `_display` + dimensions | `resolve_fk_display_names` | Correspondance normalisée | FK numériques remplies | `etl/load.py` |
| 13 | Chargement des tickets | DataFrame résolu | `load_tickets` | `ON CONFLICT (id) DO UPDATE` | `dim_tickets_enriched` | `etl/load.py` |
| 14 | Chargement des KPI | 4 indicateurs + jour | `load_daily_kpis` | `ON CONFLICT (date)` | `fact_kpis_daily` | `etl/load.py` |
| 15 | Lecture ML | — | `read_tickets` | `SELECT * FROM dim_tickets_enriched` | DataFrame | `ml_engine/data_access.py` |
| 16 | Variables | DataFrame tickets | `features.py` | 4 constructeurs | 4 jeux de variables | `ml_engine/features.py` |
| 17 | Inférence | Variables | 4 modules `models/` | RandomForest / Prophet / XGBoost / DBSCAN | 4 DataFrames de prédictions | `ml_engine/models/` |
| 18 | Recommandations | 4 DataFrames + tickets | `generate_recommendations` | 4 règles YAML | DataFrame de recommandations | `ml_engine/recommender.py` |
| 19 | Chargement ML | 5 DataFrames | `ml_engine/load.py` | Staging + `CAST(... AS JSONB)` + upsert | 5 tables | `ml_engine/load.py` |
| 20 | Requête API | HTTP GET + JWT | Routeur → `queries/` | Vérification du cache, SQL agrégé | Modèle Pydantic | `api/routers/`, `api/queries/` |
| 21 | Mise en cache | Réponse | `cache_set` | `SETEX` avec TTL du palier | Clé `glpi:api:<tier>:<clé>` | `api/cache.py` |
| 22 | Diffusion d'alerte | Nouvelle ligne `CRITIQUE` | `AlertBroadcaster._poll_once` | Sondage à 10 s au-delà du repère | Trame `WsAlert` | `api/alerts/broadcaster.py` |
| 23 | Adaptation frontend | JSON de l'API | `toOverview` / `remapTab` | Renommage, valeurs par défaut | Modèles TypeScript | `frontend/.../dashboard.service.ts` |
| 24 | Rendu | Modèles TypeScript | Composants de page | Chart.js, tableaux, cartes KPI | Interface utilisateur | `frontend/src/app/pages/` |

### 11.3 Diagramme de séquence — chargement de la Vue d'ensemble

```mermaid
sequenceDiagram
    autonumber
    actor U as Utilisateur (DSI)
    participant NG as Angular (Layer 5)
    participant API as FastAPI (Layer 4)
    participant RD as Redis
    participant PG as PostgreSQL glpi_dw

    U->>NG: Saisie des identifiants
    NG->>API: POST /api/auth/login {username, password}
    API->>PG: SELECT id, username, password_hash, role FROM api_users
    PG-->>API: ligne
    API->>API: bcrypt.verify + création des jetons JWT
    API-->>NG: {access_token, refresh_token, expires_in}
    NG->>NG: stockage dans localStorage, signal accessToken

    NG->>API: GET /api/overview (Authorization: Bearer ...)
    API->>API: decode_token + require_role(DSI/MANAGER/DIRECTION)
    API->>PG: SELECT id, username, role FROM api_users
    API->>RD: GET glpi:api:overview:<clé>
    alt Cache présent
        RD-->>API: JSON
    else Cache absent
        API->>PG: 6 requêtes agrégées (KPI, sites, catégories,<br/>demandeurs, SLA techniciens, alertes)
        PG-->>API: lignes
        API->>RD: SETEX (TTL 60 s)
    end
    API-->>NG: OverviewResponse {kpis, charts, alerts}
    NG->>NG: toOverview() puis rendu Chart.js

    NG->>API: WS /ws/alerts?token=...
    API->>API: decode_token, vérification type="access"
    API-->>NG: accept + enregistrement du client

    loop toutes les 10 s
        API->>PG: SELECT ... WHERE severity='CRITIQUE'<br/>AND created_at > :since
        PG-->>API: nouvelles recommandations
        API-->>NG: trame WsAlert
        NG->>U: toast + incrément du badge
    end
```

### 11.4 Diagramme de séquence — cycle complet d'ingestion et d'inférence

```mermaid
sequenceDiagram
    autonumber
    participant SCH as Airflow Scheduler
    participant W as Airflow Worker
    participant G as GLPI
    participant CW as Worker Celery ETL
    participant PG as PostgreSQL
    participant ML as Tâches ML

    Note over SCH: DAG glpi_polling — toutes les 10 min
    SCH->>W: extract_tickets_task
    W->>G: initSession
    G-->>W: session_token
    loop pagination
        W->>G: GET /search/Ticket?forcedisplay[]=...&range=a-b
        G-->>W: {data, totalcount}
    end
    W->>G: killSession
    SCH->>W: extract_dims_task / extract_followups_task
    SCH->>W: transform_task
    W->>CW: etl.transform_tickets.delay(rows)
    CW->>CW: TicketTransformer + compute_kpis
    CW-->>W: {records, kpis}
    SCH->>W: load_postgres_task
    W->>CW: etl.load_dimensions (EN PREMIER)
    CW->>PG: upsert dim_users/entities/categories/groups
    W->>CW: etl.load_tickets
    CW->>PG: SELECT sur les dimensions (résolution des libellés)
    CW->>PG: upsert dim_tickets_enriched
    W->>CW: etl.load_kpis
    CW->>PG: upsert fact_kpis_daily

    Note over SCH: DAG ml_inference — toutes les heures, 1 tâche à la fois
    SCH->>ML: check_data_freshness
    ML->>PG: COUNT(*) WHERE date_mod >= NOW() - 24h
    SCH->>ML: classify_users → forecast → sla_risk → cluster
    ML->>PG: SELECT * FROM dim_tickets_enriched
    ML->>ML: MLflow load_production_model (ou entraînement à la volée)
    SCH->>ML: generate_recommendations
    SCH->>ML: load_ml_results
    ML->>PG: upsert ml_* + recommendations
```

---

## 12. Communication entre les couches

| Liaison | Protocole | Format | Authentification | Fréquence | Appelant | Appelé |
| --- | --- | --- | --- | --- | --- | --- |
| **GLPI → Layer 1** | HTTP/HTTPS (`requests`) | JSON | `App-Token` + `Authorization: user_token`, puis `Session-Token` | à chaque exécution du DAG (10 min) | `GLPIClient` | API REST GLPI |
| **Layer 1 → Layer 2** | Import Python en processus | `list[dict]` | — | à chaque tâche | tâches du DAG | `glpi_connector` |
| **Layer 2 interne (DAG ↔ Celery)** | AMQP-like sur Redis | JSON | — | à chaque exécution | tâches Airflow | `glpi-etl-worker` |
| **Layer 2 interne (tâche ↔ tâche)** | XCom Airflow (base de métadonnées) | JSON sérialisé | — | à chaque exécution | Airflow | Airflow |
| **Layer 2 → PostgreSQL** | TCP 5432, SQLAlchemy + psycopg2 | SQL | utilisateur `glpi` / mot de passe | à chaque exécution | `etl/load.py` | `glpi_dw` |
| **Layer 2 → Layer 3** | **Via la base `glpi_dw`** | Tables SQL | — | asynchrone (horaire) | — | — |
| **Layer 3 → PostgreSQL** | TCP 5432, SQLAlchemy + psycopg2 | SQL / JSONB | utilisateur `glpi` | horaire | `ml_engine/` | `glpi_dw` |
| **Layer 3 ↔ MLflow** | SQLite sur volume partagé + artefacts fichier | — | — | inférence / réentraînement | `registry.py` | `mlruns` |
| **Layer 3 → Layer 4** | **Via la base `glpi_dw`** | Tables SQL | — | à la demande | — | — |
| **Layer 4 → PostgreSQL** | TCP 5432, SQLAlchemy 2.x **async** + asyncpg | SQL | utilisateur `glpi` | à chaque requête non cachée | `api/queries/` | `glpi_dw` |
| **Layer 4 → Redis** | TCP 6379, `redis.asyncio` | JSON | — | à chaque requête cachée | `api/cache.py` | Redis db 0 |
| **Layer 4 → Layer 5** | HTTP/1.1 REST | JSON | `Authorization: Bearer <JWT>` | à chaque interaction | Angular | FastAPI |
| **Layer 4 → Layer 5 (temps réel)** | WebSocket | JSON | `?token=<JWT d'accès>` | sondage serveur toutes les 10 s | FastAPI | Angular |

**Observation architecturale majeure** : les liaisons L2 → L3 et L3 → L4 ne sont pas des appels.
Le **schéma de la base `glpi_dw` est le contrat d'interface** entre ces trois couches. Cela
apporte un découplage temporel fort (chaque couche tourne à son propre rythme) mais impose que
toute évolution de schéma soit coordonnée entre le producteur et les consommateurs.

---

## 13. APIs

### 13.1 API consommée — GLPI REST

`Source : glpi_connector/client.py`

| Endpoint | Méthode | Paramètres | Usage |
| --- | --- | --- | --- |
| `/initSession` | GET | en-têtes `App-Token`, `Authorization: user_token` | Ouverture de session |
| `/killSession` | GET | en-têtes `App-Token`, `Session-Token` | Fermeture de session |
| `/search/{itemtype}` | GET | `forcedisplay[]`, `range=a-b`, `criteria[i][k]` | Extraction des tickets |
| `/{itemtype}` | GET | `expand_dropdowns`, `range=a-b` | Tables de référence |
| `/{itemtype}/{id}` | GET | `expand_dropdowns` | Élément unitaire |

Types d'objets réellement extraits : `Ticket`, `User`, `Entity`, `ITILCategory`, `Group`,
`ITILFollowup` (repli `TicketFollowup`).

Les scripts `scripts/populate_glpi.py` et `scripts/fix_ticket_services.py` utilisent en plus des
méthodes **d'écriture** (`POST /Ticket`, `POST /Ticket_User`, `POST /Group_Ticket`, …) mais ce
sont des outils de préparation de jeu de démonstration, **hors du pipeline de production**.

### 13.2 API exposée — Layer 4

Voir le tableau complet au § 9.5. Points complémentaires :

- **Documentation interactive** : Swagger UI sur `/docs`, ReDoc sur `/redoc`, schéma OpenAPI
  généré automatiquement à partir des modèles Pydantic et des dépendances.
- **En-tête de corrélation** : chaque réponse porte `X-Request-ID`.
- **Enveloppe d'erreur uniforme** : `{"error": {"code", "message", "details"}}`.
- **Codes de statut** : `200`, `401` (jeton absent/invalide/expiré), `403` (rôle insuffisant),
  `404` (recommandation inexistante), `422` (validation), `429` (débit dépassé), `500`
  (erreur interne), `503` (`/health/db` en échec).

### 13.3 Contrat WebSocket

`Source : api/schemas/common.py::WsAlert`, `api/routers/websocket.py`

- URL : `ws://<hôte>:8000/ws/alerts?token=<jeton_acces>`
- Sens : **serveur → client uniquement**. Le serveur lit les trames entrantes (`receive_text`)
  mais les ignore, uniquement pour maintenir la connexion ouverte.
- Charge utile :
  ```json
  {
    "type": "alert",
    "severity": "CRITIQUE",
    "title": "...",
    "description": "...",
    "recommendation_id": "...",
    "timestamp": "2026-08-13T10:00:00"
  }
  ```
- Fermeture sur jeton invalide : code `1008` (violation de politique).

---

## 14. Bases de données et données

### 14.1 Inventaire des systèmes de stockage

| Système | Rôle | Persistance | Source |
| --- | --- | --- | --- |
| PostgreSQL 16 — base `glpi_dw` | Entrepôt : `dim_*`, `fact_*`, `ml_*`, `recommendations`, `api_users`, `recommendation_acks` | volume `postgres-data` | `docker-compose.yml`, `scripts/init-postgres.sh` |
| PostgreSQL 16 — base `airflow` | Métabase Airflow (DAG runs, XCom, backend de résultats Celery) | même volume | `docker-compose.yml` |
| Redis 7 — db 0 | Cache API (Layer 4), broker Celery ETL | non persisté | `docker-compose.yml` |
| Redis 7 — db 1 | Broker Celery Airflow | non persisté | `docker-compose.yml` |
| SQLite `mlflow.db` | Backend de suivi et registre MLflow | volume `mlruns` | `docker-compose.yml`, `Dockerfile.airflow` |
| Système de fichiers `mlruns/artifacts` | Artefacts de modèles MLflow | volume `mlruns` | `docker-compose.yml` |
| Volume `airflow-logs` | Journaux de tâches Airflow | volume nommé | `docker-compose.yml` |
| `localStorage` navigateur | Jetons, rôle, thème, état de la barre latérale, préférences de notification | client | `frontend/.../auth.service.ts` |

**Aucun data lake, aucun fichier CSV ni JSON intermédiaire de données** n'a été trouvé dans le
dépôt. Les seuls fichiers de données présents sont `scripts/.populate_state.json` (état du script
de peuplement GLPI) et `frontend/src/assets/i18n/fr.json` (traductions). Le pipeline est
intégralement base-de-données-à-base-de-données.

### 14.2 Modèle de données de l'entrepôt `glpi_dw`

```mermaid
erDiagram
    dim_tickets_enriched }o--|| dim_users : "user_requester / user_assign"
    dim_tickets_enriched }o--|| dim_entities : "entities_id"
    dim_tickets_enriched }o--|| dim_categories : "itilcategories_id"
    dim_tickets_enriched }o--|| dim_groups : "groups_id_requester"

    ml_user_profiles }o--|| dim_users : "user_id"
    ml_sla_risk }o--|| dim_users : "technician_id"
    ml_forecasts }o--|| dim_categories : "category_id"

    recommendations }o--o| dim_users : "target_user_id"
    recommendations }o--o| dim_groups : "target_group_id"
    recommendations }o--o| dim_categories : "target_category_id"
    recommendation_acks }o--|| recommendations : "recommendation_id"
    recommendation_acks }o--|| api_users : "user_id"

    dim_tickets_enriched {
        BIGINT id PK
        TEXT name
        TEXT content
        INTEGER status
        INTEGER type
        INTEGER priority
        BIGINT itilcategories_id FK
        TIMESTAMP date
        TIMESTAMP solvedate
        TIMESTAMP time_to_resolve
        BIGINT user_requester FK
        BIGINT user_assign FK
        BIGINT entities_id FK
        BOOLEAN is_resolved
        BOOLEAN is_high_priority
        DOUBLE resolution_days
        TEXT name_normalized
    }
    ml_user_profiles {
        BIGINT user_id PK
        TEXT profile
        DOUBLE confidence
        JSONB features_snapshot
    }
    ml_clusters {
        BIGINT cluster_id PK
        TEXT algorithm PK
        JSONB sample_titles
        BIGINT ticket_count
        JSONB top_keywords
        TEXT severity
        DOUBLE neg_ratio
    }
    recommendations {
        TEXT id PK
        TEXT type
        TEXT severity
        TEXT title
        JSONB evidence
        TIMESTAMP created_at
        TIMESTAMP expires_at
    }
    api_users {
        BIGSERIAL id PK
        TEXT username UK
        TEXT password_hash
        TEXT role
    }
```

**Remarque** : les relations ci-dessus sont **logiques**. Aucune contrainte `FOREIGN KEY` n'est
déclarée entre `dim_tickets_enriched` et les dimensions dans `etl/schema.sql` — les jointures
sont réalisées applicativement en `LEFT JOIN` par le Layer 4. La seule contrainte de clé
étrangère réellement déclarée est `recommendation_acks.user_id → api_users(id) ON DELETE
CASCADE`. `Source : api/migrations/api_users_and_acks.sql`

### 14.3 Récapitulatif des tables par propriétaire

| Propriétaire (écriture) | Tables | Lecteurs |
| --- | --- | --- |
| **Layer 2** | `dim_tickets_enriched`, `dim_users`, `dim_entities`, `dim_categories`, `dim_groups`, `fact_kpis_daily` | Layer 3, Layer 4 |
| **Layer 3** | `ml_user_profiles`, `ml_forecasts`, `ml_sla_risk`, `ml_clusters`, `recommendations` | Layer 4 |
| **Layer 4** | `api_users`, `recommendation_acks` | Layer 4 uniquement |

*Note* : `fact_kpis_daily` est écrite par le Layer 2 mais aucune requête du Layer 4 ne la lit
dans le code analysé — les KPI de la Vue d'ensemble sont recalculés à la volée depuis
`dim_tickets_enriched`. La table constitue donc un historique quotidien disponible mais non
encore exploité par l'API.

### 14.4 Conventions GLPI encodées dans les données

`Source : etl/transform.py`, `ml_engine/features.py`, `api/queries/shared.py`

| Champ | Valeurs | Signification |
| --- | --- | --- |
| `status` | 5, 6 | 5 = résolu, 6 = clos ; tout le reste = ouvert |
| `type` | 1, 2 | 1 = incident, 2 = demande |
| `priority` | 5, 6 | 5 = très haute, 6 = majeure |
| `entities_id` | 0 | « Root entity » — pas un site réel, exclue des classements |
| `time_to_resolve` | `TIMESTAMP` | **échéance SLA**, pas une durée |
| `itilcategories_id` | `NULL` | état légitime — rendu « Sans catégorie » par l'API |

Ces trois conventions sont réimplémentées de façon **cohérente** dans les trois couches, ce qui
est vérifiable en comparant `etl/transform.py::RESOLVED_STATUSES`,
`ml_engine/features.py::RESOLVED_STATUSES` et `api/queries/shared.py::IS_OPEN_EXPR`.

---

## 15. Technologies utilisées

Chaque technologie listée ci-dessous est **présente dans le dépôt** ; la colonne « Emplacement »
donne le fichier qui l'atteste.

### 15.1 Langages

| Technologie | Emplacement | Pourquoi | Communique avec |
| --- | --- | --- | --- |
| **Python 3.11** | `Dockerfile.airflow` (`apache/airflow:2.9.3-python3.11`), `Dockerfile.api` (`python:3.11-slim`) | Langage des Layers 1 à 4 | tout le back-end |
| **TypeScript 5.4** | `frontend/package.json`, `tsconfig.json` | Langage du Layer 5 | API REST/WS |
| **SQL (PostgreSQL)** | `etl/schema.sql`, `ml_engine/schema.sql`, `api/queries/*.py`, `api/schema_indexes.sql` | DDL et requêtes analytiques | Layers 2, 3, 4 |
| **YAML** | `docker-compose.yml`, `ml_engine/rules.yaml` | Orchestration et règles métier | Compose, moteur de règles |
| **Bash** | `scripts/init-postgres.sh` | Initialisation de la base | PostgreSQL |

### 15.2 Layer 1

| Technologie | Emplacement | Rôle |
| --- | --- | --- |
| `requests` ≥ 2.31 | `glpi_connector/client.py` | Client HTTP vers GLPI |
| `python-dotenv` ≥ 1.0 | `glpi_connector/config.py` | Lecture du fichier `.env` |
| `requests-mock` ≥ 1.11 | `glpi_connector/tests/` | Tests sans réseau |
| **API REST GLPI** | endpoints `/initSession`, `/search/{itemtype}`… | Système source |

### 15.3 Layer 2

| Technologie | Emplacement | Rôle |
| --- | --- | --- |
| **Apache Airflow 2.9.3** | `Dockerfile.airflow`, `etl/dags/` | Ordonnancement (API TaskFlow, décorateurs `@dag`/`@task`) |
| **Celery** ≥ 5.3 | `etl/tasks.py`, service `glpi-etl-worker` | Exécution asynchrone des traitements lourds |
| **Redis 7** | `docker-compose.yml`, `etl/cache.py` | Broker Celery (db 0 ETL, db 1 Airflow) + cache |
| **pandas** ≥ 2.1 | `etl/transform.py` | Transformation tabulaire |
| **NumPy** ≥ 1.26 | `etl/transform.py` | Support numérique |
| **SQLAlchemy** (1.4 dans l'image Airflow) | `etl/load.py` (`create_engine(..., future=True)`) | Accès base |
| **psycopg2-binary** ≥ 2.9 | `requirements.txt`, `Dockerfile.airflow` | Pilote PostgreSQL synchrone |
| **PostgreSQL 16** | `docker-compose.yml` (`postgres:16-alpine`) | Entrepôt + métabase Airflow |
| `apache-airflow-providers-postgres` | `requirements.txt` | Connexion `postgres_glpi` |
| `fakeredis` ≥ 2.21 | `etl/tests/test_cache.py` | Tests du cache |

### 15.4 Layer 3

| Technologie | Emplacement | Rôle |
| --- | --- | --- |
| **scikit-learn** ≥ 1.4 | `classifier.py`, `clusterer.py` | RandomForest, DBSCAN, K-Means, TF-IDF, métriques |
| **XGBoost** ≥ 2.0 | `sla_risk.py` | Classifieur de risque SLA |
| **Prophet** ≥ 1.1 | `forecaster.py` | Prévision de séries temporelles |
| **spaCy** ≥ 3.7 + `fr_core_news_sm` | `clusterer.py`, `Dockerfile.airflow` | Lemmatisation française |
| **sentence-transformers** ≥ 2.7 | `clusterer.py` | Embeddings multilingues |
| **transformers** ≥ 4.40 | `requirements.txt` | Dépendance de sentence-transformers |
| **PyTorch** ≥ 2.2 (roues CPU) | `Dockerfile.airflow` (`--extra-index-url .../whl/cpu`) | Support des embeddings |
| **MLflow** ≥ 2.12, < 3 | `registry.py`, service `mlflow-ui` | Suivi d'expériences et registre de modèles |
| **SQLite** | `sqlite:////opt/airflow/mlruns/mlflow.db` | Backend du registre MLflow |
| **PyYAML** ≥ 6.0 | `recommender.py` | Chargement de `rules.yaml` |

**Modèle d'embeddings retenu** : `paraphrase-multilingual-MiniLM-L12-v2`, préféré à CamemBERT
car compatible français, d'environ 470 Mo, exécutable sur CPU, et encodable en une ligne. Les
poids sont pré-téléchargés dans l'image Docker afin que l'inférence ne les retélécharge jamais.
`Source : Dockerfile.airflow`, `README.md`

### 15.5 Layer 4

| Technologie | Emplacement | Rôle |
| --- | --- | --- |
| **FastAPI** ≥ 0.111 | `api/main.py` | Framework web asynchrone |
| **Uvicorn** ≥ 0.30 | `docker-compose.yml` (dev) | Serveur ASGI |
| **Gunicorn** ≥ 22.0 | `Dockerfile.api` (prod, 4 workers) | Gestionnaire de processus |
| **SQLAlchemy 2.x** (async) | `api/database.py` | `create_async_engine`, `async_sessionmaker` |
| **asyncpg** ≥ 0.29 | `api/config.py` (coercition d'URL) | Pilote PostgreSQL asynchrone |
| **Pydantic v2** ≥ 2.7 | `api/schemas/` | Validation et sérialisation |
| **pydantic-settings** ≥ 2.2 | `api/config.py` | Configuration typée depuis l'environnement |
| **python-jose[cryptography]** ≥ 3.3 | `api/security.py` | Encodage/décodage JWT (HS256) |
| **passlib[bcrypt]** ≥ 1.7 | `api/security.py` | Hachage bcrypt des mots de passe |
| **slowapi** ≥ 0.1.9 | `api/main.py` | Limitation de débit |
| **prometheus-fastapi-instrumentator** ≥ 7.0 | `api/main.py` | Métriques sur `/metrics` |
| **redis.asyncio** | `api/cache.py` | Cache asynchrone |
| `httpx`, `pytest-asyncio` | `api/requirements-api.txt` | Tests |

### 15.6 Layer 5

| Technologie | Emplacement | Rôle |
| --- | --- | --- |
| **Angular 17.3** (standalone) | `frontend/package.json`, `app.config.ts` | Framework SPA |
| **RxJS 7.8** | services `core/services/` | Flux asynchrones |
| **Signals Angular** | `auth.service.ts`, composants de page | Gestion d'état réactive |
| **Chart.js 4.5 + ng2-charts 5.0** | `app.config.ts`, composants de graphiques | Visualisations |
| **lucide-angular** | `app.config.ts` (30 icônes) | Iconographie |
| **SweetAlert2 11** | `notification.service.ts` | Toasts et boîtes de dialogue |
| **@fontsource/inter**, **jetbrains-mono** | `package.json` | Polices embarquées localement |
| **date-fns 4** | `package.json` | Manipulation de dates |
| **@angular/cdk 17** | `package.json` | Primitives d'interface |
| **Karma + Jasmine** | `package.json`, `*.spec.ts` | Tests unitaires |

### 15.7 Infrastructure

| Technologie | Emplacement | Rôle |
| --- | --- | --- |
| **Docker / docker-compose** | `docker-compose.yml`, 2 Dockerfiles | Orchestration locale de 9 services |
| **postgres:16-alpine** | `docker-compose.yml` | Base de données |
| **redis:7-alpine** | `docker-compose.yml` | Cache et broker |
| **apache/airflow:2.9.3-python3.11** | `Dockerfile.airflow` | Image de base ETL/ML |
| **python:3.11-slim** | `Dockerfile.api` | Image de base API |

### 15.8 Technologies explicitement absentes

Pour lever toute ambiguïté, les technologies suivantes, souvent associées à ce type de projet,
**ne sont pas présentes** dans le dépôt : Kafka, Spark, dbt, Snowflake, Elasticsearch, MongoDB,
Power BI, Tableau, Grafana, Kubernetes, Terraform, React, Vue, Node.js côté serveur, Java,
CI/CD (aucun répertoire `.github/workflows`, `.gitlab-ci.yml` ni `Jenkinsfile`).

Prometheus est **partiellement** présent : l'API expose des métriques au format Prometheus sur
`/metrics`, mais **aucun serveur Prometheus ni Grafana** n'est déclaré dans `docker-compose.yml`.

---

## 16. Sécurité

### 16.1 Authentification

| Frontière | Mécanisme | Source |
| --- | --- | --- |
| GLPI → Layer 1 | App-Token (client d'API) + User-Token personnel, puis Session-Token | `glpi_connector/client.py` |
| Layer 5 → Layer 4 (REST) | JWT `HS256`, jeton d'accès 30 min, jeton de rafraîchissement 7 j | `api/security.py` |
| Layer 5 → Layer 4 (WebSocket) | Jeton d'accès en paramètre d'URL, vérifié avant acceptation | `api/routers/websocket.py` |
| Layers 2/3/4 → PostgreSQL | Utilisateur `glpi` / mot de passe, via l'URL de connexion | `docker-compose.yml` |
| Airflow UI | Utilisateur `admin` créé par `airflow-init` | `docker-compose.yml` |

### 16.2 Autorisation

Trois rôles applicatifs : `DSI`, `MANAGER`, `DIRECTION`, contraints par un `CHECK` SQL.
La règle d'accès est implémentée par la fabrique de dépendances `require_role(*allowed)` :

- Lecture de tous les onglets, prédictions et recommandations : les **trois** rôles.
- Acquittement d'une recommandation : **DSI et MANAGER uniquement** (`403` sinon).

`Source : api/security.py`, `api/routers/recommendations.py`

Côté frontend, `authGuard` protège toutes les routes hors `/login` et `roleGuard` est disponible
pour restreindre par rôle (actuellement configuré avec une liste vide sur `/settings`, donc sans
restriction effective). Le contrôle d'accès **réel** est celui du serveur ; les gardes Angular ne
sont qu'un confort d'interface.

### 16.3 Gestion des secrets

| Secret | Emplacement | Remarque |
| --- | --- | --- |
| `GLPI_APP_TOKEN`, `GLPI_USER_TOKEN` | `.env`, jamais en dur | `.env.example` ne contient que des valeurs de remplacement |
| `API_JWT_SECRET` | `.env`, défaut `change-me-in-prod` | **doit** être remplacé en production ; le README propose `openssl rand -hex 32` |
| Mots de passe utilisateurs | `api_users.password_hash` (bcrypt) | jamais stockés en clair |
| Mots de passe PostgreSQL | `docker-compose.yml` (`glpi`/`glpi`, `airflow`/`airflow`) | valeurs de développement |
| `.gitignore` | présent à la racine | protège `.env` du versionnement |

### 16.4 Validation des entrées

- **Layer 4** : validation intégrale par Pydantic v2 sur les corps de requête et les paramètres,
  avec bornes explicites (`limit: ge=1, le=500`, `entity_id: ge=0`, `category_id: ge=0`). Une
  entrée invalide renvoie un `422` structuré.
- **Requêtes SQL** : toutes les valeurs variables passent par des **paramètres liés**
  (`:start_date`, `:limit`, `:uid`…), jamais par interpolation de chaîne. Seuls les fragments
  **statiques** (alias de table, expressions constantes) sont interpolés. L'injection SQL est
  donc structurellement écartée sur les chemins analysés.
- **Layer 1** : les trois variables obligatoires sont validées au démarrage, avec message
  explicite listant les manquantes.

### 16.5 Autres protections

| Mesure | Implémentation | Source |
| --- | --- | --- |
| CORS restreint | Liste blanche `API_ALLOWED_ORIGINS`, défaut `http://localhost:4200` | `api/main.py`, `api/config.py` |
| Limitation de débit | 100/min anonyme (par IP), 300/min authentifié (par jeton) | `api/main.py` |
| Non-divulgation d'erreurs | Enveloppe `{"error": {...}}`, aucune trace de pile | `api/main.py::_error` |
| Vérification TLS vers GLPI | `verify_ssl` activé par défaut | `glpi_connector/config.py` |
| Révocation implicite | `get_current_user` revérifie l'existence de l'utilisateur à chaque requête | `api/security.py` |
| Séparation des privilèges d'écriture | L'API ne peut pas écrire dans `dim_*` ni `ml_*` (aucun `INSERT`/`UPDATE` dans `api/queries/` hors `recommendation_acks`) | `api/queries/` |

### 16.6 Points d'attention identifiés

1. Les identifiants de démonstration (`dsi@sartex` / `dsi-dev-password`, etc.) sont documentés
   dans le code et le README ; ils doivent être supprimés ou modifiés avant tout déploiement
   réel. Le code les marque explicitement « DEV DEFAULTS ONLY ».
2. `API_JWT_SECRET` a une valeur par défaut faible (`change-me-in-prod`).
3. Les mots de passe PostgreSQL de `docker-compose.yml` sont des valeurs de développement.
4. `AIRFLOW__WEBSERVER__SECRET_KEY: "change-me"` et `AIRFLOW__WEBSERVER__EXPOSE_CONFIG: "true"`
   sont des réglages de développement.
5. Aucun mécanisme de révocation de jeton (liste de refus) n'est implémenté : un jeton d'accès
   volé reste valide jusqu'à son expiration, au maximum 30 minutes.
6. L'API expose `/metrics` sans authentification.

Ces points relèvent d'une configuration de développement assumée ; ils sont signalés ici parce
qu'ils devraient être traités lors d'un passage en production.

---

## 17. Gestion des erreurs et journalisation

### 17.1 Synthèse par couche

| Couche | Stratégie dominante | Mécanismes |
| --- | --- | --- |
| **Layer 1** | Réessayer puis lever une exception typée | 3 tentatives, délai exponentiel 1,5^n, réouverture de session sur 401, 5 classes d'exception |
| **Layer 2** | Rejouer la tâche | `retries=2` Airflow, `task_acks_late` Celery, résolution de FK tolérante avec comptage des échecs |
| **Layer 3** | **Dégrader gracieusement** | Replis pour chaque modèle, `load_production_model` renvoyant `None`, garde de démarrage à froid |
| **Layer 4** | Enveloppe d'erreur uniforme | 4 gestionnaires d'exception + capture dans le middleware, dégradation silencieuse du cache |
| **Layer 5** | État d'erreur visible, jamais de plantage | Signals `error` par page, toasts, rafraîchissement automatique du jeton, reconnexion WebSocket |

### 17.2 Journalisation

| Couche | Format | Particularité |
| --- | --- | --- |
| Layers 1, 2, 3 | `logging` standard, `getLogger(__name__)` | Volumes traités en `INFO`, anomalies en `WARNING` ; sous Airflow, les journaux sont capturés par tâche dans `/opt/airflow/logs/dag_id=…/run_id=…/task_id=…/attempt=N.log` |
| Layer 4 | **JSON structuré** | Champs `level`, `logger`, `message`, `request_id`, `user`, `route`, `duration_ms`, `exc` ; corrélation par `ContextVar` |
| Layer 5 | Toasts SweetAlert2 | Pas de journalisation serveur |

### 17.3 Observabilité disponible

- `GET /health` — vivacité de l'API.
- `GET /health/db` — accessibilité de PostgreSQL (`503` si injoignable).
- `GET /metrics` — métriques Prometheus (durées, compteurs par route et statut).
- En-tête `X-Request-ID` sur chaque réponse, permettant de relier un incident signalé par un
  utilisateur aux lignes de journal correspondantes.
- Healthchecks Docker sur `postgres`, `redis`, `airflow-webserver` et `api`.
- Interface Airflow (port 8080) et interface MLflow (port 5000).

Aucun système d'agrégation de journaux (ELK, Loki) ni de traçage distribué (OpenTelemetry,
Jaeger) n'est présent dans le dépôt.

---

## 18. Déploiement

### 18.1 Images Docker

**`Dockerfile.airflow`** — base `apache/airflow:2.9.3-python3.11`, construite en trois étapes :

1. Dépendances ETL installées **avec le fichier de contraintes officiel d'Airflow**, pour ne pas
   remonter accidentellement SQLAlchemy ou Flask et casser Airflow. SQLAlchemy et Celery ne sont
   **pas** réépinglés — Airflow les fournit déjà.
2. Dépendances ML installées **sans** ce fichier de contraintes (la pile ML exige des versions
   plus récentes), avec MLflow épinglé `<3` et PyTorch en roues **CPU**
   (`--extra-index-url https://download.pytorch.org/whl/cpu`), puis
   `python -m spacy download fr_core_news_sm`.
3. Pré-chargement du modèle sentence-transformers dans `/opt/airflow/.model_cache`, et création
   de `/opt/airflow/mlruns/artifacts` **dans l'image**.

**Pourquoi créer `mlruns` dans l'image** (commentaire explicite du Dockerfile) : un volume nommé
monté sur un répertoire existant de l'image hérite du propriétaire de ce répertoire. Si le chemin
était absent, Docker le créerait appartenant à `root` et toutes les tâches ML échoueraient avec
`sqlite3.OperationalError: unable to open database file`, le conteneur tournant sous l'uid 50000.

**`Dockerfile.api`** — base `python:3.11-slim`. Installe uniquement `api/requirements-api.txt`,
puis copie `api/`, `glpi_connector/`, `etl/`, `ml_engine/`. Commande par défaut : gunicorn avec
4 workers uvicorn sur le port 8000.

### 18.2 Procédure de mise en service

Séquence reconstituée à partir du `README.md` et des fichiers de configuration :

```bash
# 1. Configuration
cp .env.example .env          # renseigner GLPI_BASE_URL, GLPI_APP_TOKEN, GLPI_USER_TOKEN

# 2. Vérification de la connexion GLPI (Layer 1)
python scripts/test_connection.py          # code de sortie 0 = câblage correct

# 3. Démarrage de la pile (Layers 2, 3, 4)
docker compose build
docker compose up -d                       # attendre ~60 s la fin de airflow-init

# 4. Tables ML (Layer 3)
docker compose exec airflow-worker python -m ml_engine.migrate

# 5. Tables API + utilisateurs de test (Layer 4)
psql "postgresql://glpi:glpi@localhost:5432/glpi_dw" -f api/migrations/api_users_and_acks.sql
python -m api.migrations.seed_users

# 6. Déclenchement des DAGs depuis l'interface Airflow (http://localhost:8080)
#    glpi_polling  puis  ml_inference

# 7. Frontend (Layer 5)
cd frontend && npm install && npm start     # http://localhost:4200
```

### 18.3 Cartographie des ports

| Port | Service | Interface |
| --- | --- | --- |
| 4200 | `ng serve` (hors Docker) | Tableau de bord Angular |
| 5000 | `mlflow-ui` | Interface MLflow |
| 5432 | `postgres` | Base de données |
| 6379 | `redis` | Cache et broker |
| 8000 | `api` | API REST + `/docs` + WebSocket |
| 8080 | `airflow-webserver` | Interface Airflow |

**Conflit documenté** : le port 8080 est également le port habituel d'une instance GLPI locale.
Les deux ne peuvent coexister que si GLPI s'attache à `127.0.0.1` et Docker au joker ; sinon il
faut remapper l'un des deux. `Source : README.md`

### 18.4 Résilience et dimensionnement

- Tous les services portent `restart: unless-stopped`, sauf `airflow-init` (`restart: "no"`).
  Le commentaire du fichier précise que sans cela, un redémarrage de Docker Desktop relance les
  conteneurs applicatifs mais laisse les bases éteintes, la pile paraissant alors saine à moitié.
- Healthchecks : `pg_isready` sur `postgres`, `redis-cli ping` sur `redis`, `/health` HTTP sur
  `airflow-webserver` et `api`.
- Dépendances conditionnelles : les services Airflow attendent
  `airflow-init: service_completed_successfully` ; `api` attend `postgres` et `redis` sains.
- **Dimensionnement indiqué dans le README** : la pile complète (9 conteneurs) demande environ
  **6 Go** alloués à Docker, et cette allocation doit rester nettement inférieure à la RAM totale
  de l'hôte. Sur une machine contrainte, `mlflow-ui` et `airflow-webserver` peuvent être arrêtés
  (~500 Mo libérés) : ce sont des interfaces de confort, les DAGs fonctionnent sans elles.

### 18.5 Absence de chaîne CI/CD

Aucun fichier de pipeline d'intégration ou de déploiement continu n'existe dans le dépôt
(pas de `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`, `azure-pipelines.yml`). Les tests
sont exécutés manuellement via `pytest` et `npm test`. Il n'existe pas non plus de manifeste
Kubernetes ni de configuration d'infrastructure-as-code.


---

## 19. Configuration

### 19.1 Variables d'environnement, par couche

`Source : .env.example`, `docker-compose.yml`, modules `config.py` de chaque couche

**Layer 1 — connexion GLPI**

| Variable | Défaut | Obligatoire |
| --- | --- | --- |
| `GLPI_BASE_URL` | — | **oui** |
| `GLPI_APP_TOKEN` | — | **oui** |
| `GLPI_USER_TOKEN` | — | **oui** |
| `GLPI_BASE_URL_CONTAINER` | `http://host.docker.internal:8080/api.php/v1` | non |
| `GLPI_PAGE_SIZE` | `100` | non |
| `GLPI_TIMEOUT` | `30` | non |
| `GLPI_MAX_RETRIES` | `3` | non |
| `GLPI_RETRY_BACKOFF` | `1.5` | non |
| `GLPI_VERIFY_SSL` | `true` | non |

**Layers 2 et 3 — stockage**

| Variable | Défaut | Portée |
| --- | --- | --- |
| `POSTGRES_URL` | `postgresql+psycopg2://glpi:glpi@postgres:5432/glpi_dw` | L2, L3, L4 (coercie en asyncpg) |
| `REDIS_URL` | `redis://redis:6379/0` | L2, L4 |
| `CACHE_TTL_LIVE` | `300` | L2 |
| `CACHE_TTL_AGG` | `3600` | L2 |

**Layer 3 — moteur ML**

| Variable | Défaut local | Valeur sous compose |
| --- | --- | --- |
| `MLFLOW_TRACKING_URI` | `sqlite:///mlflow.db` | `sqlite:////opt/airflow/mlruns/mlflow.db` |
| `MLFLOW_ARTIFACT_ROOT` | `./mlartifacts` | `file:/opt/airflow/mlruns/artifacts` |
| `ML_MODEL_CACHE_DIR` | `./.model_cache` | `/opt/airflow/.model_cache` |
| `ML_COLD_START_MIN_ROWS` | `100` | idem |
| `ML_EMBEDDING_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | idem |
| `ML_SPACY_MODEL` | `fr_core_news_sm` | idem |
| `ML_TOP_N_CATEGORIES` | `10` | idem |
| `ML_KMEANS_K` | `10` | idem |
| `ML_RANDOM_STATE` | `42` | idem |

**Layer 4 — API** : voir le tableau du § 9.4.

**Layer 5 — frontend** : configuration par fichier TypeScript, pas par variables d'environnement
(`apiBaseUrl`, `wsBaseUrl` dans `src/environments/environment.ts` et `environment.prod.ts`).

### 19.2 Configuration Airflow injectée par compose

`Source : docker-compose.yml`, bloc `x-airflow-common`

| Clé | Valeur | Effet |
| --- | --- | --- |
| `AIRFLOW__CORE__EXECUTOR` | `CeleryExecutor` | Exécution distribuée |
| `AIRFLOW__DATABASE__SQL_ALCHEMY_CONN` | `postgresql+psycopg2://airflow:airflow@postgres:5432/airflow` | Métabase |
| `AIRFLOW__CELERY__BROKER_URL` | `redis://redis:6379/1` | Broker (db 1) |
| `AIRFLOW__CELERY__RESULT_BACKEND` | `db+postgresql://airflow:airflow@postgres:5432/airflow` | Résultats |
| `AIRFLOW__CELERY__WORKER_CONCURRENCY` | `1` | **Une seule tâche lourde à la fois** |
| `AIRFLOW__CORE__LOAD_EXAMPLES` | `false` | Pas de DAG d'exemple |
| `PYTHONPATH` | `/opt/airflow` | Import des packages projet |

Le commentaire du fichier explique le réglage de concurrence : Celery lance par défaut un
processus par CPU (12 sur la machine de référence), et chaque processus fils détient un import
complet d'Airflow (~700 Mo) **avant même** de dupliquer le sous-processus qui exécute réellement
les bibliothèques ML. Sur une petite machine virtuelle Docker, cela provoque un arrêt OOM se
manifestant par un code de sortie 1 **sans aucune trace Python**.

### 19.3 Montages de volumes Airflow

```
./etl/dags       → /opt/airflow/dags/etl
./ml_engine/dags → /opt/airflow/dags/ml_engine
./etl            → /opt/airflow/etl
./ml_engine      → /opt/airflow/ml_engine
./glpi_connector → /opt/airflow/glpi_connector
mlruns           → /opt/airflow/mlruns
airflow-logs     → /opt/airflow/logs
```

Les DAGs des Layers 2 et 3 sont donc montés dans deux sous-répertoires distincts du dossier de
DAGs, et les trois packages Python sont montés à la racine du `PYTHONPATH`. Aucun volume n'est
monté sur `/opt/airflow/.model_cache` : le modèle d'embeddings français est cuit dans l'image
afin que l'inférence ne le retélécharge jamais.

### 19.4 Fichiers de configuration hors environnement

| Fichier | Rôle |
| --- | --- |
| `ml_engine/rules.yaml` | Seuils métier des 4 règles de recommandation — modifiables sans toucher au code |
| `frontend/src/environments/environment{,.prod}.ts` | URLs de l'API et du WebSocket |
| `frontend/angular.json`, `tsconfig*.json` | Configuration de build Angular |
| `api/pytest.ini` | Configuration pytest du Layer 4 |
| `api/schema_indexes.sql` | Index de performance optionnels, à appliquer après revue |
| `.gitignore` | Exclusion de `.env` et des artefacts |

---

## 20. Dépendances

### 20.1 Dépendances entre packages du dépôt

```mermaid
flowchart LR
    GC["glpi_connector"]
    ETL["etl"]
    ML["ml_engine"]
    API["api"]
    FE["frontend"]
    SCR["scripts"]

    ETL -->|"import GLPIClient, extractors,<br/>GLPIConfig"| GC
    SCR -->|"import GLPIClient, GLPIConfig"| GC
    ML -.->|"aucun import Python ;<br/>couplage par la base"| ETL
    API -.->|"aucun import ;<br/>couplage par la base"| ML
    FE -->|"HTTP + WebSocket"| API
```

**Constat vérifié dans le code** : la seule dépendance d'import Python entre packages est
`etl` → `glpi_connector` (dans `etl/config.py` et dans les tâches du DAG), plus
`scripts` → `glpi_connector`. `ml_engine` n'importe **jamais** `etl`, et `api` n'importe
**jamais** `ml_engine` ni `etl` pour ses traitements — il redéclare ses propres conventions dans
`api/queries/shared.py`.

*Nuance* : `Dockerfile.api` copie tout de même `glpi_connector/`, `etl/` et `ml_engine/` dans
l'image, ce que le commentaire justifie par « the layer-1/2/3 packages it imports config helpers
from ». Dans le code effectivement analysé de `api/`, aucun import de ces packages n'apparaît :
la copie est conservatrice.

Ce très faible couplage est une **qualité architecturale** : chaque couche peut être testée,
déployée et faire évoluer ses dépendances indépendamment — c'est précisément ce qui permet à
l'API d'utiliser SQLAlchemy 2.x pendant que l'ETL reste en 1.4.

### 20.2 Les deux jeux de dépendances Python

| Fichier | Portée | Contrainte structurante |
| --- | --- | --- |
| `requirements.txt` | Layers 1, 2, 3 (+ 4 pour un usage local) | SQLAlchemy suit Airflow 2.9.3 (1.4) ; MLflow épinglé `>=2.12,<3` |
| `api/requirements-api.txt` | Layer 4 uniquement | SQLAlchemy `>=2.0` + asyncpg |

Ce dédoublement est la conséquence directe d'un conflit de versions réel, explicité dans les
commentaires des deux fichiers et dans `Dockerfile.api` : Airflow 2.9.3 impose SQLAlchemy 1.4,
tandis que le moteur asynchrone de l'API exige SQLAlchemy 2.x. Les deux ne peuvent pas cohabiter
dans un même environnement Python, d'où **deux images Docker distinctes**.

### 20.3 Couverture de tests

| Couche | Répertoire | Nombre de tests | Approche |
| --- | --- | --- | --- |
| Layer 1 | `glpi_connector/tests/` | 12 | `requests-mock` — aucun réseau, aucune instance GLPI |
| Layer 2 | `etl/tests/` | 11 | transform en pandas pur, cache avec `fakeredis`, load sur SQLite |
| Layer 3 | `ml_engine/tests/` | 33 | petits DataFrames synthétiques, aucun PostgreSQL, aucun GPU |
| Layer 4 | `api/tests/` | 42 | base de données simulée (`get_session` surchargé), **JWT réel** |
| Layer 5 | `frontend/src/**/*.spec.ts` | 1 spécification par composant | Karma + Jasmine |
| **Total back-end** | | **98 tests** | |

Le README précise pour le Layer 4 : « Every endpoint has happy-path, auth-failure,
invalid-param and empty-result coverage, plus WebSocket accept/reject and broadcaster fan-out
tests. » L'inventaire des fichiers de test confirme cette structure
(`test_auth`, `test_overview`, `test_tabs`, `test_demandeurs`, `test_repetitifs`,
`test_recommendations`, `test_websocket`, `test_health`).

---

## 21. Tableau récapitulatif des composants

| Couche | Composant | Fichier | Rôle | Entrée | Sortie |
| --- | --- | --- | --- | --- | --- |
| L1 | `GLPIConfig` | `glpi_connector/config.py` | Configuration validée | variables d'environnement | dataclass gelée |
| L1 | `GLPIClient` | `glpi_connector/client.py` | Session, réessais, pagination | `GLPIConfig` | lignes JSON brutes |
| L1 | `extract_tickets` | `glpi_connector/extractors.py` | Remappage des options GLPI | client | `list[dict]` (19 champs) |
| L1 | `extract_users/entities/categories/groups` | `glpi_connector/extractors.py` | Tables de référence | client | 4 `list[dict]` |
| L1 | `extract_ticket_followups` | `glpi_connector/extractors.py` | Suivis ITIL, repli de version | client | `list[dict]` |
| L1 | Exceptions | `glpi_connector/exceptions.py` | Typage des erreurs | — | 5 classes |
| L2 | DAG `glpi_polling` | `etl/dags/glpi_polling_dag.py` | Orchestration 10 min | déclencheur cron | résumé de chargement |
| L2 | `TicketTransformer` | `etl/transform.py` | Nettoyage et enrichissement | `list[dict]` | DataFrame + KPI |
| L2 | `flatten_glpi_value` | `etl/transform.py` | Aplatissement des cellules multivaluées | valeur GLPI | scalaire |
| L2 | `normalize_title` | `etl/transform.py` | Normalisation des titres | titre | titre normalisé |
| L2 | `resolve_fk_display_names` | `etl/load.py` | Libellés → identifiants | DataFrame + dimensions | DataFrame à FK résolues |
| L2 | `_upsert_via_staging` | `etl/load.py` | Chargement idempotent | DataFrame | nombre de lignes |
| L2 | `GLPICache` | `etl/cache.py` | Cache Redis 2 paliers (disponible, non branché) | clé/valeur | JSON |
| L2 | Tâches Celery | `etl/tasks.py` | Exécution asynchrone | JSON | JSON |
| L2 | Schéma entrepôt | `etl/schema.sql` | DDL | — | 6 tables, 4 index |
| L3 | `MLConfig` | `ml_engine/config.py` | Configuration ML | variables d'environnement | dataclass gelée |
| L3 | `read_tickets` | `ml_engine/data_access.py` | Lecture de l'entrepôt | moteur | DataFrame |
| L3 | `build_user_features` | `ml_engine/features.py` | 9 variables par demandeur | tickets | DataFrame indexé |
| L3 | `build_daily_category_counts` | `ml_engine/features.py` | Séries journalières par catégorie | tickets | `{cat: [ds, y]}` |
| L3 | `build_sla_features` | `ml_engine/features.py` | 5 variables + étiquette par technicien | tickets | DataFrame indexé |
| L3 | `build_text_corpus` | `ml_engine/features.py` | Corpus textuel | tickets | DataFrame `[id, text]` |
| L3 | `classifier` | `ml_engine/models/classifier.py` | Profils demandeurs (RandomForest) | variables | `[user_id, profile, confidence, snapshot]` |
| L3 | `forecaster` | `ml_engine/models/forecaster.py` | Volume 72 h (Prophet) | séries | `[category_id, forecast_date, …]` |
| L3 | `sla_risk` | `ml_engine/models/sla_risk.py` | Risque SLA 48 h (XGBoost) | variables | `[technician_id, risk_score, …]` |
| L3 | `clusterer` | `ml_engine/models/clusterer.py` | Causes racines (NLP + DBSCAN) | corpus | `[cluster_id, keywords, severity, …]` |
| L3 | `recommender` | `ml_engine/recommender.py` | Moteur de règles | 4 DataFrames + tickets | recommandations |
| L3 | `rules.yaml` | `ml_engine/rules.yaml` | Seuils métier | — | dictionnaire |
| L3 | `registry` | `ml_engine/registry.py` | MLflow | modèle + métriques | version enregistrée |
| L3 | DAG `ml_inference` | `ml_engine/dags/ml_inference_dag.py` | Inférence horaire | cron | tables `ml_*` |
| L3 | DAG `ml_retrain` | `ml_engine/dags/ml_retrain_dag.py` | Réentraînement hebdomadaire | cron | versions promues |
| L4 | `create_app` | `api/main.py` | Fabrique d'application | réglages | application FastAPI |
| L4 | `Settings` | `api/config.py` | Configuration typée | environnement | objet de réglages |
| L4 | `get_session` | `api/database.py` | Session async par requête | — | `AsyncSession` |
| L4 | `security` | `api/security.py` | JWT, bcrypt, rôles | jeton / identifiants | `CurrentUser` ou 401/403 |
| L4 | `cache` | `api/cache.py` | Cache Redis async | clé | JSON ou `None` |
| L4 | `queries/shared` | `api/queries/shared.py` | Fragments SQL communs | filtres | `WHERE` + paramètres |
| L4 | `queries/overview` | `api/queries/overview.py` | 6 requêtes agrégées | filtres | `OverviewResponse` |
| L4 | `queries/tabs` | `api/queries/tabs.py` | 6 requêtes d'onglet | filtres | réponses typées |
| L4 | `queries/predictions` | `api/queries/predictions.py` | Prévisions et risques | filtres | réponses typées |
| L4 | `queries/recommendations` | `api/queries/recommendations.py` | Liste et acquittement | filtres, `user_id` | réponses typées |
| L4 | `AlertBroadcaster` | `api/alerts/broadcaster.py` | Sondage + diffusion WebSocket | `recommendations` | trames `WsAlert` |
| L4 | `logging_config` | `api/logging_config.py` | Journaux JSON corrélés | événements | lignes JSON |
| L5 | `ApiService` | `.../core/services/api.service.ts` | Client HTTP | chemin + paramètres | `Observable<T>` |
| L5 | `AuthService` | `.../core/services/auth.service.ts` | Authentification, signals | identifiants | jetons, rôle |
| L5 | `DashboardService` | `.../core/services/dashboard.service.ts` | Adaptation API → modèles | JSON | modèles TypeScript |
| L5 | `WebsocketService` | `.../core/services/websocket.service.ts` | Alertes temps réel | trames WS | signals `unread`, `alerts` |
| L5 | 3 intercepteurs | `.../core/interceptors/` | JWT, rafraîchissement, erreurs | requête/réponse | requête enrichie, toast |
| L5 | `authGuard` / `roleGuard` | `.../core/guards/` | Protection des routes | état d'authentification | `true` ou redirection |
| L5 | 9 pages | `.../pages/` | Onglets analytiques | données de l'API | interface |
| L5 | 13 composants partagés | `.../shared/components/` | Cartes KPI, tableaux, graphiques | entrées | rendu |

---

## 22. Diagrammes complémentaires

### 22.1 Diagramme de dépendances des composants

```mermaid
flowchart TB
    subgraph EXT["Systèmes externes"]
        GLPI["GLPI"]
        BROWSER["Navigateur"]
    end

    subgraph INFRA["Infrastructure"]
        PG[("PostgreSQL 16<br/>glpi_dw + airflow")]
        RD[("Redis 7<br/>db0 + db1")]
        MLF[("MLflow<br/>SQLite + artefacts")]
    end

    subgraph CODE["Packages applicatifs"]
        GC["glpi_connector"]
        ETL["etl"]
        ML["ml_engine"]
        API["api"]
        FE["frontend"]
    end

    subgraph ORCH["Orchestration"]
        SCHED["airflow-scheduler"]
        WORK["airflow-worker"]
        EWORK["glpi-etl-worker"]
    end

    GLPI -->|HTTP| GC
    GC -->|import| ETL
    SCHED --> WORK
    WORK --> ETL
    WORK --> ML
    ETL -->|"Celery"| RD --> EWORK --> PG
    ETL --> PG
    ML --> PG
    ML <--> MLF
    API --> PG
    API --> RD
    FE -->|"REST + WS"| API
    BROWSER --> FE
```

### 22.2 Diagramme d'état d'une recommandation

```mermaid
stateDiagram-v2
    [*] --> Générée : ml_inference déclenche une règle<br/>(recommender.py)
    Générée --> Persistée : upsert ON CONFLICT (id)<br/>(ml_engine/load.py)
    Persistée --> Diffusée : severity = CRITIQUE<br/>détectée par le sondeur 10 s
    Persistée --> Affichée : GET /api/recommendations<br/>ou /api/overview (top 4)
    Diffusée --> Affichée : toast + badge<br/>(WebsocketService)
    Affichée --> Acquittée : POST /{id}/acknowledge<br/>par un DSI ou MANAGER
    Acquittée --> [*] : expires_at dépassé<br/>(14 jours)
    Affichée --> [*] : expires_at dépassé
    Persistée --> Persistée : réexécution de l'inférence<br/>→ mise à jour, pas de doublon<br/>(id = hachage déterministe)
```

### 22.3 Diagramme du cycle de vie d'un modèle ML

```mermaid
flowchart LR
    A["ml_retrain<br/>dimanche 02:00"]
    B["mod.train(df)"]
    C{"Démarrage<br/>à froid ?"}
    D["mod.evaluate(df)"]
    E["registry.log_run<br/>→ nouvelle version"]
    F{"Métrique<br/>améliorée ?"}
    G["promote_to_production<br/>archivage des versions précédentes"]
    H["Version conservée<br/>hors Production"]
    I["ml_inference<br/>chaque heure"]
    J["load_production_model"]
    K{"Modèle<br/>trouvé ?"}
    L["Entraînement à la volée"]
    M["predict → tables ml_*"]

    A --> B --> C
    C -->|oui| H
    C -->|non| D --> E --> F
    F -->|oui| G
    F -->|non| H
    I --> J --> K
    K -->|oui| M
    K -->|non| L --> M
    G -.->|"stade Production"| J
```

---

## 23. Exemple de parcours d'une donnée

Ce scénario suit un ticket unique, de sa création dans GLPI jusqu'à son influence sur une alerte
affichée au DSI. Chaque étape est rattachée à son fichier.

**T0 — Dans GLPI.** Un utilisateur ouvre le ticket #4821, intitulé
« RE: Impossible de se connecter à l'ERP », catégorie *ERP > Connexion*, entité *Usine A*,
priorité 5, type 1 (incident).

**T0 + ≤ 10 min — Extraction (Layer 1).** Le DAG `glpi_polling` se déclenche.
`extract_tickets_task` ouvre une session, puis `client.search("Ticket", forcedisplay=[…])`
pagine `/search/Ticket`. GLPI renvoie pour ce ticket une ligne dont les clés sont des chaînes
numériques :

```json
{"2": 4821, "1": "RE: Impossible de se connecter à l'ERP", "12": 2, "14": 1,
 "3": 5, "7": "ERP > Connexion", "80": "Root entity > Usine A",
 "4": "Dupont Marie", "15": "2026-08-13 08:12:00", ...}
```

`Source : glpi_connector/client.py::search`

`_remap` applique `TICKET_FIELD_MAP` et produit :

```python
{"id": 4821, "name": "RE: Impossible de se connecter à l'ERP", "status": 2,
 "type": 1, "priority": 5, "itilcategories_id": "ERP > Connexion",
 "entities_id": "Root entity > Usine A", "_users_id_requester": "Dupont Marie",
 "date": "2026-08-13 08:12:00", ...}
```

`Source : glpi_connector/extractors.py::_remap`

**T1 — Transformation (Layer 2).** La ligne part vers Celery. `TicketTransformer` :

1. renomme `_users_id_requester` → `user_requester` ;
2. convertit `date` en `datetime64` ;
3. `coerce_fk_ids` conserve `itilcategories_id_display = "erp > connexion"` et
   `entities_id_display = "root entity > usine a"`, et met les colonnes numériques à `NA` ;
4. `add_derived` calcule `is_resolved = False` (statut 2 ∉ {5, 6}),
   `is_high_priority = True` (priorité 5 ∈ {5, 6}), `resolution_days = NaN`,
   et `name_normalized = "impossible de se connecter à l'erp"` — le préfixe `RE:` a été retiré.

`Source : etl/transform.py`

**T2 — Chargement (Layer 2).** `load_dimensions_task` s'exécute d'abord. Puis
`resolve_fk_display_names` construit le dictionnaire de `dim_categories` et y trouve
`"erp > connexion"` → `17`, et dans `dim_entities` `"root entity > usine a"` → `2`. Le ticket
est inséré dans `dim_tickets_enriched` avec `itilcategories_id = 17`, `entities_id = 2`,
`user_requester = 3041`.

`Source : etl/load.py::resolve_fk_display_names`, `load_tickets`

**T3 — Intelligence (Layer 3).** À l'heure suivante, `ml_inference` démarre.

- `build_user_features` agrège tous les tickets de Marie Dupont : ce ticket incrémente
  `total_tickets`, `incidents_count` et `high_priority_count`. Son `name_normalized` étant déjà
  apparu 4 fois, il compte dans `repetitive_count`.
- Le RandomForest la classe `critique` avec une confiance de 0,91 → ligne dans
  `ml_user_profiles`.
- `build_text_corpus` produit le texte « RE: Impossible de se connecter à l'ERP. … » ; spaCy le
  lemmatise, sentence-transformers le vectorise, DBSCAN le regroupe avec 137 tickets similaires
  → cluster #3, `severity = "CRITIQUE"` (≥ 100), `top_keywords = ["erp", "connexion",
  "authentification", …]`, `neg_ratio = 0,72` (le mot « impossible » est dans `_NEG_WORDS`).

`Source : ml_engine/features.py`, `models/classifier.py`, `models/clusterer.py`

**T4 — Recommandations (Layer 3).** `generate_recommendations` applique les règles :

- Règle `cause_racine` : cluster DBSCAN de 137 tickets ≥ 100, vu dans les 30 derniers jours →
  recommandation `CAUSE_RACINE`, sévérité `CRITIQUE`, titre
  « Cause racine détectée (cluster 3) », `id = sha1("CAUSE_RACINE|None|None|None")[:20]`.
- Règle `formation` : Marie est `critique` et 84 % de ses incidents portent sur 2 catégories →
  recommandation `FORMATION`, sévérité `ÉLEVÉ`, ciblant `target_user_id = 3041`.

`evidence_to_json` sérialise les preuves, puis `load_recommendations` insère les deux lignes avec
`ON CONFLICT (id) DO UPDATE`.

`Source : ml_engine/recommender.py`, `ml_engine/load.py`

**T5 — Diffusion (Layer 4).** Dans les 10 secondes, `AlertBroadcaster._poll_once` détecte la
nouvelle ligne `CRITIQUE` dont `created_at > _last_seen`, et diffuse à tous les clients WebSocket
connectés :

```json
{"type":"alert","severity":"CRITIQUE","title":"Cause racine détectée (cluster 3)",
 "description":"137 tickets similaires. Mots-clés: [...]",
 "recommendation_id":"a3f9...","timestamp":"2026-08-13T09:15:03"}
```

`Source : api/alerts/broadcaster.py`

**T6 — Restitution (Layer 5).** Le `WebsocketService` reçoit la trame, l'ajoute au tampon,
incrémente le badge de la cloche et affiche un toast `error` (la sévérité contient « crit »). En
parallèle, le rechargement de `/api/overview` fait apparaître :

- le KPI *Tickets répétitifs* augmenté de 137 (somme de `ml_clusters.ticket_count`) ;
- Marie Dupont dans le graphique *Top demandeurs*, avec le badge de profil `critique` dans
  l'onglet Demandeurs ;
- l'onglet *Répétitifs* affichant le cluster #3 avec sa sévérité et ses mots-clés ;
- l'alerte en tête du panneau, avec un bouton d'acquittement.

`Source : frontend/.../websocket.service.ts`, `dashboard.service.ts`, `api/queries/overview.py`

**T7 — Acquittement.** Le DSI clique. Angular émet
`POST /api/recommendations/a3f9…/acknowledge` avec son jeton porteur. L'API vérifie le rôle
(`DSI` ∈ `{DSI, MANAGER}`), vérifie l'existence de la recommandation (`404` sinon), insère dans
`recommendation_acks` avec `ON CONFLICT (recommendation_id, user_id) DO UPDATE`, puis invalide
le cache `overview`. La réponse confirme l'horodatage.

`Source : api/routers/recommendations.py`, `api/queries/recommendations.py::acknowledge`

**Délai total** : environ 10 minutes pour que le ticket atteigne l'entrepôt, jusqu'à 1 heure de
plus pour qu'il influence les modèles, puis 10 secondes pour l'alerte temps réel.

---

## 24. Points importants de l'architecture

### 24.1 Forces identifiées

| # | Point fort | Élément probant |
| --- | --- | --- |
| 1 | **Couplage minimal entre couches** | Une seule dépendance d'import inter-packages (`etl` → `glpi_connector`) ; L2/L3/L4 communiquent par la base |
| 2 | **Isolation assumée des dépendances** | Deux images Docker et deux fichiers de dépendances pour résoudre un conflit SQLAlchemy réel |
| 3 | **Idempotence de bout en bout** | Tout chargement passe par `ON CONFLICT DO UPDATE` ; les identifiants de recommandation sont des hachages déterministes |
| 4 | **Dégradation gracieuse systématique** | Chaque modèle ML a un repli ; le cache tombe en « toujours manquant » ; l'API ne divulgue jamais de trace |
| 5 | **Testabilité par conception** | `transform.py`, `features.py`, `models/*.py` et `recommender.py` n'importent ni Airflow ni base ; 98 tests back-end sans réseau ni PostgreSQL |
| 6 | **Reproductibilité ML** | `random_state=42` partout, empreinte du DataFrame d'entrée journalisée dans MLflow, promotion conditionnée à l'amélioration métrique |
| 7 | **Règles métier externalisées** | Les 4 seuils de recommandation vivent dans `rules.yaml`, modifiables sans redéploiement de code |
| 8 | **Sécurité par défaut côté serveur** | Chaque point d'entrée de données porte un `Depends(require_role(...))` ; les requêtes SQL n'utilisent que des paramètres liés |
| 9 | **Observabilité utilisable** | Journaux JSON corrélés par `X-Request-ID`, sondes de santé, métriques Prometheus |
| 10 | **Documentation des pièges** | Les commentaires du code expliquent le *pourquoi* des choix non évidents (ordre CORS, `start += len(data)`, `make_interval`, propriété du volume `mlruns`) |

### 24.2 Points de vigilance

| # | Point | Constat | Impact |
| --- | --- | --- | --- |
| 1 | Diffuseur WebSocket en mémoire | L'état est par processus ; documenté comme nécessitant Redis pub/sub en multi-workers | Limite l'API à un worker unique pour le temps réel |
| 2 | Contenu des suivis non persisté | `extract_ticket_followups` extrait les suivis mais le Layer 2 n'en garde que le compte | Le NLP travaille sur un texte appauvri |
| 3 | Cache Layer 2 non branché | `GLPICache` est implémenté et testé mais jamais appelé dans le flux | Composant mort dans le pipeline actuel |
| 4 | `fact_kpis_daily` non consommée | Écrite par le Layer 2, lue par aucune requête du Layer 4 | Historique quotidien disponible mais inexploité |
| 5 | `repetitive` toujours à 0 dans l'onglet Demandeurs | Commentaire du code : « per-user repetitive count not tracked in ml_clusters » | Colonne présente mais non renseignée |
| 6 | Secrets de développement | `change-me-in-prod`, `glpi/glpi`, mots de passe de démonstration | À traiter avant production |
| 7 | Absence de CI/CD | Aucun pipeline dans le dépôt | Les 98 tests dépendent d'une exécution manuelle |
| 8 | Absence de contraintes FK en base | Les relations sont applicatives seulement | L'intégrité repose sur la logique de chargement |
| 9 | `roleGuard` sans restriction | `data: { roles: [] }` sur `/settings` | Mécanisme câblé mais inactif |
| 10 | Frontend non conteneurisé | Absent de `docker-compose.yml` | Déploiement du Layer 5 à la charge de l'exploitant |

### 24.3 Décisions techniques notables et leur justification

Ces décisions sont documentées **dans le code lui-même**, ce qui en facilite la vérification :

1. **`start += len(data)` et non `start += size`** — GLPI tronque la dernière page via
   `list_limit_max` ; faire confiance à la taille demandée ferait sauter silencieusement le reste
   du jeu de données. `Source : glpi_connector/client.py`
2. **Dimensions chargées avant les tickets** — sans quoi la résolution des clés étrangères
   échoue et toutes les liaisons deviennent `NULL`. `Source : etl/dags/glpi_polling_dag.py`
3. **CORS enregistré en dernier** — Starlette encapsule à l'envers ; sinon un 500 échappe à CORS
   et le navigateur ne rapporte qu'un « 0 Unknown Error » opaque. `Source : api/main.py`
4. **`make_interval(days => :horizon)`** — asyncpg infère `(:h || ' days')::interval` comme du
   texte et rejette un entier. `Source : api/queries/predictions.py`
5. **`COALESCE` terminé par une littérale** — `'Cat #'||NULL` vaut `NULL` en SQL et casserait un
   champ Pydantic non optionnel. `Source : api/queries/tabs.py`
6. **Repli sur la colonne côté faits dans `user_name_expr`** — `COALESCE(..., u.id)` vaut `NULL`
   sur un échec de `LEFT JOIN`. `Source : api/queries/shared.py`
7. **`mlruns` créé dans l'image** — un volume monté sur un chemin absent serait créé
   propriété de `root`, rendant SQLite inaccessible à l'uid 50000.
   `Source : Dockerfile.airflow`
8. **Concurrence Celery à 1 et `max_active_tasks=1`** — évite l'arrêt OOM des tâches ML, qui se
   manifeste par un code de sortie 1 sans trace Python.
   `Source : docker-compose.yml`, `ml_engine/dags/ml_inference_dag.py`
9. **MLflow adossé à SQLite plutôt qu'à un store fichier** — un store fichier ne peut pas
   enregistrer de modèles ni gérer les stades. `Source : ml_engine/config.py`
10. **Import Airflow non déclenché dans `ml_engine/config.py`** — un import partiel casse le
    store SQLite de MLflow. `Source : ml_engine/config.py`

---

## 25. Conclusion

### 25.1 Synthèse

GlpiInteligence est un **pipeline analytique et prédictif en cinq couches** construit au-dessus
d'une instance GLPI, dont l'analyse du code confirme la structure annoncée :

- **Layer 1** (`glpi_connector`) extrait les données GLPI par son API REST, avec une gestion
  soignée de la session, des réessais et de la pagination.
- **Layer 2** (`etl`) transforme ces données avec pandas, résout la difficulté des libellés
  d'affichage GLPI, et alimente de manière idempotente un entrepôt PostgreSQL toutes les
  10 minutes, orchestré par Airflow et exécuté par Celery.
- **Layer 3** (`ml_engine`) applique quatre familles de modèles — RandomForest, Prophet,
  XGBoost, DBSCAN sur embeddings français — puis un moteur de règles YAML qui produit des
  recommandations actionnables, le tout versionné dans MLflow.
- **Layer 4** (`api`) sert ces résultats via une API FastAPI asynchrone sécurisée par JWT et
  contrôle d'accès par rôle, avec cache Redis, limitation de débit, journaux JSON corrélés et
  un flux WebSocket d'alertes temps réel.
- **Layer 5** (`frontend`) restitue l'ensemble dans une SPA Angular 17 à sept onglets
  analytiques, thémable, avec alertes temps réel et export CSV.

### 25.2 Qualité de la réalisation

L'analyse fait ressortir une base de code cohérente et mature pour un projet de cette portée :

- **98 tests back-end** couvrant les quatre couches Python, exécutables sans réseau, sans
  PostgreSQL et sans GPU, plus une spécification Karma par composant Angular.
- Un **découplage réel et vérifiable** entre couches, avec une seule dépendance d'import
  inter-packages.
- Une **gestion des erreurs pensée par couche** : réessais en amont, dégradation gracieuse au
  milieu, enveloppe uniforme et non divulgation en aval.
- Une **documentation du *pourquoi*** dans les commentaires du code, qui explique dix décisions
  techniques non évidentes et les modes de défaillance associés — c'est un atout majeur pour la
  maintenance.

### 25.3 Perspectives

Les évolutions naturelles, telles qu'elles ressortent du code et de ses annotations :

1. **Persister le contenu des suivis** dans une table `dim_followups` — le point d'accroche est
   déjà prévu dans `features.build_text_corpus`, et enrichirait significativement le NLP.
2. **Passer le diffuseur d'alertes à Redis pub/sub** pour autoriser plusieurs workers en
   production — piste explicitement notée dans `api/alerts/broadcaster.py`.
3. **Brancher ou retirer `GLPICache`** dans le flux d'ingestion, aujourd'hui implémenté mais
   inutilisé.
4. **Exploiter `fact_kpis_daily`** pour les séries temporelles de KPI, aujourd'hui recalculées à
   la volée.
5. **Renseigner le compteur `repetitive` par utilisateur** dans l'onglet Demandeurs.
6. **Durcir la configuration de production** : secrets, comptes de démonstration, clé Airflow.
7. **Ajouter une chaîne CI/CD** exécutant automatiquement les 98 tests existants.
8. **Conteneuriser le frontend** pour compléter le `docker-compose.yml`.

### 25.4 Remarque finale sur la méthode

Ce rapport a été établi par lecture directe du code source. Les informations non déterminables à
partir du dépôt — notamment les métriques réelles des modèles sur des données de production, les
volumes effectivement traités et l'environnement de déploiement cible — n'ont volontairement pas
été extrapolées. Toute affirmation technique du document est rattachée à un fichier vérifiable,
afin que le superviseur puisse en contrôler l'exactitude.
