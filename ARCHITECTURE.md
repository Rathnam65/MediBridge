# MediBridge Architecture

## Request flow

`Browser → FastAPI REST API → Agent Pipeline → SQLite → Browser`

### Agent pipeline

1. **Clinical Understanding Agent** (`backend/services/pipeline.py`)
   - Extracts diagnoses, symptoms, procedures, medications and negations.
2. **Coding & Retrieval Agent**
   - Searches the structured ICD-10-CM / HCPCS demo knowledge catalog.
3. **Validation & Explanation Agent**
   - Calculates confidence, identifies documentation gaps and marks low-confidence results for human review.
4. **Human-in-the-loop**
   - Coder can mark a case `Validated`, `Review`, or `Pending`.

## Backend modules

- `backend/main.py` — HTTP/API layer and static frontend hosting
- `backend/schemas.py` — request validation models
- `backend/database.py` — SQLite connection/schema initialization
- `backend/services/pipeline.py` — modular analysis pipeline and demo coding catalog

## API

- `GET /api/health`
- `GET /api/dashboard`
- `GET /api/cases`
- `GET /api/cases/{case_id}`
- `POST /api/analyze/text`
- `POST /api/analyze/file`
- `POST /api/cases/{case_id}/decision`
- `GET /api/codes`
- `GET /api/agents`
- `GET /api/activity`
- `GET /docs`

## Production hardening still required

The supplied project is a functional academic prototype. Before real clinical deployment, add authentication/authorization, PHI controls, encrypted storage, audit/security controls, licensed official coding datasets, validated coding rules, a real LLM/RAG layer, robust PDF/DOCX ingestion, monitoring and a formal clinical evaluation process.
