# Existing Technology Stack

## Runtime and frameworks

- Python source; documented minimum is Python 3.10.
- Local environment observed: Python 3.13.7.
- Docker base image: `python:3.12-slim`.
- FastAPI ASGI application with Uvicorn; requirements declare minimums rather than pinned versions (`fastapi>=0.115`, `uvicorn[standard]>=0.30`).
- Local installed versions observed in the workspace: FastAPI 0.141.1, Uvicorn 0.52.4, python-multipart 0.0.32, python-dotenv 1.2.3.
- Pydantic request validation is brought in through FastAPI; SQLite access uses Python's standard-library `sqlite3`.
- Browser client uses plain HTML, CSS, and JavaScript. No package manifest or frontend build system is present.

## Storage, data, and document handling

- SQLite database path is configurable through `DATABASE_PATH`; default is `database/medibridge.db`.
- Catalogs are versioned JSON under `data/coding/`; ICD-10-CM and HCPCS records load at process startup.
- Text, JSON, Markdown, CSV, and LOG uploads are decoded as text. PDF/DOCX parsers are absent.
- Catalog preparation and synthetic demo-data import use Python standard-library parsing modules.

## Packaging and deployment

- `Dockerfile` builds a single Python application image.
- `compose.yaml` runs the application with a Caddy reverse proxy and persistent volumes.
- Environment variables configure the app name/environment, host/port, allowed origins, and database path.
- Tests use pytest and FastAPI's `TestClient`; no pytest dependency is declared in `backend/requirements.txt`.

## Not present in the current stack

No LLM SDK/runtime, LangGraph, embedding model, vector database, clinical NLP library, PDF/DOCX parser, model-serving process, or model-evaluation framework is declared or wired into the project.
