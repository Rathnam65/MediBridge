# MediBridge — Medical Coding Review Workspace

MediBridge is a self-hosted web application for medical coders. Users create an account, sign in, analyze documentation, review candidate codes and evidence, and record human decisions. Case records, activity, and preferences are isolated per account.

## Features

- Analyze pasted clinical text or uploaded TXT, JSON, Markdown, CSV, and LOG files.
- Search the configured ICD-10-CM and HCPCS reference catalogs.
- Review catalog-backed text matches, supporting excerpts, and coder-review flags. Match scores are not coding-accuracy probabilities.
- Track cases and human review decisions in a private account workspace.
- Browse cases with status filters, search, pagination, separate ICD-10-CM and HCPCS counts, and row actions. Result reports group recommendations by catalog and can be printed or saved as PDF from the browser.
- Register with an email and password; sessions use expiring HTTP-only cookies.
- Account passwords require at least 6 characters; use a longer, unique password for better security.

## Run locally

Requires Python 3.10 or later.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python run.py
```

On a fresh installation, open http://127.0.0.1:8000, create an account from the sign-up screen, then sign in. Demo accounts and cases can optionally be created as described below.

## Demo coder workload

To exercise separate coder workspaces with the supplied synthetic Synthea export, run this once using the CSV folder. The script creates ten demo accounts, distributes fifteen sample encounters among them, sets a three-day review deadline, and prints each randomly generated password once. Save the output securely; passwords are not recoverable from the database, and rerunning will not reset existing demo accounts. The import uses encounter dates and condition descriptions only; it does not store Synthea patient names, IDs, or demographics.

```powershell
python scripts/seed_synthea_demo.py "C:\path\to\synthea_sample_data_csv_nov2021\csv"
```

Sign in to a coder account and use the header notification bell to see today's assignment count, open workload, and each case deadline. Each user's notifications and cases are account-isolated.

## Coding reference data

The installed catalogs include HCPCS 2026 Q4 and ICD-10-CM 2027. The app reports which catalogs are available and only suggests codes present in installed reference data; no placeholder or built-in sample codes are used. Obtain and maintain current datasets under the applicable CMS licenses. The ICD-10-CM catalog is generated from CMS's `icd10cm_codes_2027.txt` code-description file; the importer writes `data/coding/ICD10CM/2027/codes.json`. The HCPCS importer can build the supported catalog from the CMS workbook and NOC workbook:

```powershell
python scripts/prepare_data.py ..
```

To import the supplied 2027 ICD-10-CM descriptions, pass the folder containing `icd10cm_codes_2027.txt` (or a parent folder containing it):

```powershell
python scripts/prepare_data.py "C:\path\to\Code Descriptions"
```

The generated catalog is loaded at application startup and is included in the Docker image. Catalogs are versioned JSON reference data rather than rows in the user/workflow SQLite database. The analysis pipeline is deterministic phrase matching, not an AI model or a certified coding engine; the displayed match score only indicates a phrase match and is not a probability of coding accuracy. A qualified coder must verify every recommendation against current official references and payer/facility rules.

## Deploy with Docker

Point a DNS name at a Linux host with Docker Compose installed and inbound ports 80/443 available. Copy the deployment example to `.env`, set the real domain, then start the app and HTTPS reverse proxy:

```bash
cp .env.deploy.example .env
# Edit .env and set APP_DOMAIN to your DNS name
docker compose up --build -d
```

The included Caddy reverse proxy obtains and renews HTTPS certificates automatically when DNS points to the host. Create the first coder account from the sign-up screen. The app container is not directly published to the internet; SQLite and TLS state persist in Docker volumes. Back up `medibridge-data` securely and test restores. Use one app instance and one Uvicorn worker with SQLite.

For local development, follow the Python setup in the “Run locally” section; it uses `127.0.0.1:8000` and does not require Docker or a domain.

## Deploy the guide demo on Render

The free Render web service has ephemeral local storage, so this deployment uses managed PostgreSQL (Neon Free) instead of SQLite. The repository's `render.yaml` provisions the free Render web service and marks `DATABASE_URL` as a secret that must be supplied in the dashboard.

1. Create a Neon Postgres project in the same region where possible. Copy its pooled connection string (`postgresql://...`) from the Neon dashboard.
2. Push this repository to GitHub and create a Render **Blueprint** from it.
3. In the Render service environment, set `DATABASE_URL` to the Neon connection string. `REQUIRE_POSTGRES=true` makes startup fail rather than silently using Render's temporary local filesystem if the database secret is missing. Never commit the URL or put it in a public log.
4. Deploy. The application applies the checked-in Alembic schema migration during startup; `/api/health` verifies app/database connectivity.
5. Test signup, login/logout, session expiry, account isolation, uploads, and a redeploy before sharing the URL. Keep `CLINICAL_DATA_APPROVED=false` and `SYNTHETIC_DEMO_ENABLED=true`.

The application still supports local SQLite when `DATABASE_URL` is blank and `REQUIRE_POSTGRES` is false. The currently existing local `database/medibridge.db` is not automatically copied to Neon; do not use patient information in this research demo. Neon Free is intended for prototypes, can scale to zero, and has limited recovery/backup capabilities. Before deploying, arrange and test a separate backup/restore process for the selected account and retain copies outside the database provider. Neither this free configuration nor the demo is suitable for real patient data or production clinical use. Render Free services can spin down and have no persistent local disk.

## Privacy and production readiness

Authentication and per-account access controls do not by themselves make an installation HIPAA-compliant or suitable for protected health information (PHI). Before any PHI use, complete an organization-specific security and privacy assessment, encryption-at-rest and backup strategy, retention/deletion policy, monitoring and incident response, access/role management, and legal/compliance review.

This is a research prototype. Clinical accuracy has not been established through coder-adjudicated evaluation; it is not a validated clinical AI system and must not be used for clinical decisions. This release has no organization/team sharing, MFA, password reset, administrator provisioning, or formal compliance certification. Clinical document analysis is disabled by default. It remains disabled unless `CLINICAL_DATA_APPROVED=true` **and** a reviewed JSON file records references for clinical governance, privacy/security review, clinician sign-off, local-model verification, evaluation, and backup/retention review. The example approval file contains no approvals. This engineering gate only checks that evidence is recorded; it cannot verify that an institution approved it or establish regulatory compliance. Do not process real patient data in this classroom prototype. Existing databases from earlier versions may contain unassigned legacy records; those records are not visible to new accounts.

## Classroom prototype setup

The analysis workflow is a research prototype: rule-based clinical context extraction, hybrid lexical/index/semantic retrieval, optional loopback-only Ollama reasoning, and a LangGraph sequence that always ends in required human review. Clinical accuracy has not been established by coder-adjudicated evaluation.

**Ollama setup (optional):** Install Ollama locally, then pull a reasoning model and an embedding model, for example `ollama pull qwen2.5:3b` and `ollama pull nomic-embed-text`. Set `LOCAL_MODEL_NAME=qwen2.5:3b` and `OLLAMA_EMBEDDING_MODEL=nomic-embed-text` in `.env`. Keep `LOCAL_MODEL_URL` on loopback (`http://127.0.0.1:11434` by default); the client rejects non-loopback hosts so note text is not sent to a remote model endpoint. `GET /api/model-status` reports local connection/model availability without submitting note text.

Build the catalog index after installing catalogs and configuring Ollama:

```powershell
python scripts/build_local_index.py
```

The index records the Ollama embedding model name and digest. Query-time retrieval checks the same identity; a missing model, changed model digest, missing index, or catalog mismatch is reported and uses an explicit lexical fallback. Do not silently reuse an index built by a different embedding model. Hybrid ranking includes lexical overlap, ICD-10-CM index terms, and semantic similarity. Tabular instructions, index citations, and HCPCS catalog references remain sourced from the installed catalogs. The built-in hash-vector adapter is retained only for isolated tests; it is no longer the production default.

**Optional trained clinical NLP:** Rule-based extraction remains the always-available fallback and continues to determine negation, history, uncertainty, temporality, and experiencer. To enable local Hugging Face disease-entity extraction, install `pip install -r requirements-clinical-nlp.txt`, download/cache `alvaroalon2/biobert_diseases_ner` once on the machine, then set `CLINICAL_NLP_MODEL` to its local model directory:

```powershell
python -c "import os; from huggingface_hub import snapshot_download; snapshot_download(repo_id='alvaroalon2/biobert_diseases_ner', local_dir=os.path.join(os.path.expanduser('~'), '.cache', 'medibridge', 'biobert_diseases_ner'))"
$env:CLINICAL_NLP_MODEL="$env:USERPROFILE\.cache\medibridge\biobert_diseases_ner"
```

The download fetches model files only; inference is configured with `local_files_only=True`, so clinical text is not sent to Hugging Face. Model detections include model confidence and provenance, while context attributes are still assigned by the existing local rules. Missing dependencies or model files are surfaced in the workflow and rule-based extraction continues. The model's training corpus and confidence do not establish clinical validity; all results require coder review.

When both optional model settings are blank, the app performs deterministic suggestions and displays that model reasoning/semantic retrieval are not configured. No model downloads automatically. `python scripts/benchmark_local_models.py` uses synthetic examples only and does not establish clinical quality.

For a guide presentation, set `SYNTHETIC_DEMO_ENABLED=true` in the deployment `.env` and keep `CLINICAL_DATA_APPROVED=false`. Visitors can use the separate public synthetic-only workflow without an account: fictional text and synthetic TXT/JSON/Markdown/CSV/LOG/PDF/DOCX files. Inputs are analyzed temporarily and are not written to cases or activity; review decisions are held only in the browser session. Text and file submissions require a synthetic-data confirmation. This confirmation is an attestation, not a PHI detector: never upload real patient records. The regular clinical text and upload APIs remain blocked by organizational approval requirements.

Import the supplied synthetic test corpus into its own SQLite file (not into coder accounts):

```powershell
python scripts/import_synthea.py "C:\path\to\synthea_sample_data_csv_nov2021\csv"
```

The importer retains hashed synthetic relationship keys and condition/encounter labels only; it omits names, addresses, demographics, and source identifiers. It can be rerun to atomically rebuild the separate database. Use `GET /api/demo/synthea` after signing in to show its version and counts.

Prepare ICD-10-CM's supplied tabular instructions and indexes with:

```powershell
python scripts/prepare_data.py "C:\path\to\2027-code-descriptions-in-tabular-order\Code Descriptions"
python scripts/prepare_data.py "C:\path\to\2027-icd-10-table-and-index"
```

The importer preserves the 2027 hierarchy, instruction notes, and source locations. The leaf/billable indicator is a demonstration heuristic, not authoritative billing validation. `python scripts/build_local_index.py` creates the optional local SQLite vector index, and `python scripts/evaluate_pipeline.py --output data/evaluation/demo-report.json` runs illustrative synthetic extraction/retrieval metrics. These fixtures are not coder-adjudicated, and the report intentionally leaves coding-accuracy metrics unavailable until an approved adjudicated set exists.

## Architecture

- Frontend: HTML, CSS, vanilla JavaScript
- Backend: FastAPI + Python
- Storage: SQLite
- Workflow: documentation analysis → reference lookup → validation → human coder review
