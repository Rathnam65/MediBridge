# Project Structure

## Project type

Full-stack, single deployable web application: static browser client, Python ASGI API, local SQLite database, and versioned JSON coding catalogs.

## Layers and functional areas

- **Browser UI** (`frontend/`): a single HTML page, vanilla JavaScript, and CSS. UI sections cover sign-in, dashboard, analysis, cases, code search, workflow, activity, and settings.
- **API/application** (`backend/main.py`, `backend/schemas.py`): FastAPI routes, authentication, account-scoped cases, activity, settings, document analysis, code search, and static-file delivery.
- **Domain/service** (`backend/services/pipeline.py`): deterministic phrase/negation extraction, catalog matching, and validation flags.
- **Persistence/configuration** (`backend/database.py`, `backend/config.py`): SQLite schema, migrations performed during initialization, and environment-derived settings.
- **Reference data** (`data/coding/`): normalized HCPCS and ICD-10-CM JSON catalogs loaded at API startup.
- **Import/maintenance CLI** (`scripts/`): CMS catalog preparation and a Synthea demo-account/case seeder.
- **Validation** (`tests/`): authentication/case ownership and reference-catalog/pipeline tests.
- **Deployment**: Docker image, Compose application plus Caddy reverse proxy, environment examples, and shell/batch local launchers.

## Entrypoints

- `run.py` starts Uvicorn and `backend.main:app`.
- `backend/main.py` initializes the database and serves API routes and the static application.
- `frontend/index.html` is the browser entry page; `frontend/app.js` handles navigation and API interactions.
- `scripts/prepare_data.py` imports supplied ICD-10-CM and HCPCS source files.
- `scripts/seed_synthea_demo.py` imports synthetic encounter-condition summaries and creates demo accounts/cases.
- `Dockerfile` / `compose.yaml` define the container and reverse-proxy deployment.

## Measured source inventory

Counts below are from direct workspace file enumeration, excluding virtual environments and bytecode from the source inventory:

| Area | Source files |
|---|---:|
| `backend/` top-level | 6 |
| `backend/services/` | 2 |
| `frontend/` | 4 |
| `scripts/` | 3 |
| `tests/` | 2 |
| Coding catalog files (JSON and placeholders) | 4 |

## Runtime shape

The application is a single FastAPI process. SQLite is the system of record. Coding catalogs are loaded from disk into process memory at import/startup; the JSON catalog files are copied into the Docker image. There is no separate model server, vector store, workflow engine, or background-job worker in the current implementation.
