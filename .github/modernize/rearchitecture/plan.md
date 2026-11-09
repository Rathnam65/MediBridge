# Implementation Plan: MediBridge Clinical Coding Intelligence and Evaluation

**Date**: 2026-11-09 | **Spec**: User-provided system-gap assessment in chat

## Summary

Extend the existing FastAPI/vanilla-JavaScript prototype from keyword-only matching toward a locally hosted, evidence-traceable coding-assistance workflow. Add validated PDF/DOCX ingestion, full synthetic-data preparation, official ICD-10-CM tabular guidance and HCPCS validation, local embeddings and retrieval, RAG, clinical-context extraction, and LangGraph orchestration. Establish benchmark and clinically adjudicated evaluation before any real-data release.

This is an engineering plan, **not approval for clinical production**. The user identified real clinical data as the eventual target but authorized engineering work only. Real-data launch and real-PHI ingestion remain blocked until the organization's clinical, privacy, security, legal, and regulatory owners approve the intended use and required controls.

## Technical Context

**Language/Version**: Python; current Docker runtime is Python 3.12; local environment observed at Python 3.13.7.  
**Primary Dependencies**: FastAPI, Uvicorn, Pydantic, SQLite; new dependencies will include a local model adapter/runtime, LangGraph, local embedding/vector-store implementation, and PDF/DOCX parsers. Pin and test versions when implementation begins.  
**Storage**: Existing SQLite user/case/workspace database; versioned JSON coding catalogs. New vector index must be local and versioned/rebuildable; preserve source provenance for every retrieved rule.  
**Testing**: pytest and FastAPI TestClient; add parser, graph, catalog, retrieval, evaluation, and browser workflow coverage.  
**Target Platform**: Existing Docker Compose + Caddy deployment, with local model inference on the same host/private network. Hardware and model are selected by benchmark before implementation is finalized.  
**Performance Goals**: No numeric service-level targets were supplied. Establish and document model latency, ingestion throughput, retrieval latency, and resource limits using the intended deployment hardware before release gates are set.  
**Constraints**: Local-only inference and embeddings; no external transmission of clinical text; do not bypass human coder decisions; do not claim clinical accuracy based on phrase-match scores; block PHI/real-data launch pending formal governance approval.

## Constitution Check

No project constitution exists in the repository. The following user-confirmed constraints govern this engineering plan until an approved organizational constitution replaces them:

- **PASS — local processing**: model and embedding operations must stay on the private/local host.
- **PASS — human review**: suggestions require coder verification; no unattended code submission.
- **PASS — launch gate**: engineering work may proceed, but real-data/PHI use must remain disabled until written organizational approvals and release criteria exist.
- **PASS — evidence and evaluation**: each recommendation must show source/catalog provenance; synthetic data alone cannot establish clinical coding accuracy.
- **BLOCKED — clinical production**: no clinical deployment readiness or regulatory/compliance claim can be made from this plan.

Re-check these constraints against the approved clinical governance and security policies before any PHI is used.

## Applied Guidelines

- No framework/language migration is requested; no matching source-to-target migration guideline applies.
- Preserve the existing account ownership and human decision workflow described in `artifacts/data-model.md` and `artifacts/wire_contracts.yaml`.
- Keep new inference, parsing, retrieval, and graph failures explicit. Do not return an empty/success-shaped result after model, index, or parser failure.

## Implementation Steps

### Phase 1: Foundation and engineering-only safeguards

#### Step 1: Define evaluation and local-runtime contracts
- **Requirements**: REQ-001, REQ-004, REQ-011, REQ-012
- **Design inputs**: `artifacts/tech-stack.md`, `artifacts/data-model.md`, `artifacts/units/clinical-analysis/behavior.yaml`; `research.md`
- **Description**: Establish a reproducible synthetic/approved-deidentified benchmark format, source provenance shape, local model endpoint/configuration contract, resource/latency measurements, and an explicit feature flag or deployment guard preventing PHI/real-data workflows before governance approval. Keep production approval external to code implementation.

- [ ] T001 [Plan:1.1] Define versioned evaluation-case and provenance schemas in `backend/schemas.py` and synthetic fixtures under `tests/fixtures/`.
- [ ] T002 [Plan:1.1] Add a documented engineering-only configuration guard and tests in `backend/config.py` and `tests/test_auth.py`; refuse real-data mode until governance approval is recorded.

#### Step 2: Add local inference and embedding adapters
- **Requirements**: REQ-001, REQ-004
- **Design inputs**: `artifacts/tech-stack.md`, `artifacts/units/clinical-analysis/unit_decomposition.yaml`; `research.md`
- **Description**: Add typed interfaces and environment-based configuration for local LLM and embedding services. Benchmark candidate local models against the synthetic task suite on the intended host before pinning a model. Disable external API fallback for clinical content and report unavailable models explicitly.

- [ ] T003 [Plan:1.2] Add a local inference client interface, endpoint/timeouts, and explicit unavailable-model errors in `backend/services/llm/client.py` and `backend/config.py`.
- [ ] T004 [Plan:1.2] Add a local embedding adapter and a reproducible candidate-model benchmark command in `backend/services/retrieval/embeddings.py` and `scripts/benchmark_local_models.py`.

#### Step 3: Introduce independently testable analysis services
- **Requirements**: REQ-002, REQ-005, REQ-011
- **Design inputs**: `artifacts/units/clinical-analysis/unit_decomposition.yaml`, `artifacts/shared_modules.yaml`
- **Description**: Separate document parsing, context extraction, candidate retrieval, rule validation, explanation, and scoring interfaces so the LangGraph nodes can be tested independently. Preserve existing behavior behind the current API while the new path is gated.

- [ ] T005 [Plan:1.3] Add typed analysis-stage interfaces and a minimal LangGraph state definition in `backend/services/workflow/graph.py`; retain `analyze_text()` compatibility in `backend/services/pipeline.py`.

### Phase 2: Clinical documents and synthetic corpus

#### Step 4: Support PDF and DOCX ingestion
- **Requirements**: REQ-006, REQ-007
- **Design inputs**: `artifacts/units/api-workflows/behavior.yaml`, `artifacts/wire_contracts.yaml`
- **Description**: Add bounded, defensive PDF and DOCX extraction with explicit unsupported, encrypted, malformed, oversized, empty, and text-extraction error responses. Preserve source page/paragraph offsets for evidence display. Keep the existing 10 MB limit unless a measured requirement approves a change.

- [x] T006 [Plan:4] Add bounded PDF and DOCX parsing with page/paragraph evidence locations in `backend/services/ingestion/` and declare only selected parsers in `backend/requirements.txt`.
- [x] T007 [Plan:4] Extend `backend/main.py` upload validation and `frontend/index.html` / `frontend/app.js` accepted file types; add parser and error-contract tests in `tests/test_medicoders.py`.

#### Step 5: Improve clinical context extraction
- **Requirements**: REQ-005
- **Design inputs**: `artifacts/units/clinical-analysis/behavior.yaml`, `artifacts/data-model.md`
- **Description**: Implement structured extraction for active vs historical conditions, negation, temporality, experiencer, uncertainty, symptoms, procedures, medications, and evidence spans. Model output must conform to validated schemas; unsupported or ambiguous assertions must be flagged for coder review, not treated as fact.

- [ ] T008 [Plan:5] Implement schema-validated context extraction and evidence spans in `backend/services/clinical_nlp/`; preserve unknown/uncertain states rather than coercing them to positive diagnoses.
- [ ] T009 [Plan:5] Add unit and regression fixtures for negation, history, temporality, experiencer, uncertainty, and conflicting evidence in `tests/test_medicoders.py`.

#### Step 6: Import the complete Synthea sample corpus for testing
- **Requirements**: REQ-008, REQ-011
- **Design inputs**: `artifacts/units/synthea-demo-seeding/behavior.yaml`, `artifacts/units/catalog-preparation/behavior.yaml`
- **Description**: Replace the demo seeder's 15-case cap with a repeatable, batchable importer for the supplied Synthea dataset. Preserve necessary patient/encounter/condition relationships in a separate synthetic test store, avoid importing unrelated identifiers/demographics, record dataset/version provenance, and support reset/rebuild. Keep synthetic records clearly labeled and isolated from real-user workspaces.

- [ ] T010 [Plan:6] Add a batchable Synthea importer for patient/encounter/condition-linked synthetic records in `scripts/import_synthea.py`; keep all imported records marked synthetic and isolated.
- [ ] T011 [Plan:6] Add import idempotency, relationship integrity, privacy-minimization, and full-corpus count tests in `tests/test_medicoders.py`.

### Phase 3: Coding knowledge and retrieval

#### Step 7: Import ICD-10-CM tabular hierarchy and instructions
- **Requirements**: REQ-009
- **Design inputs**: `artifacts/units/catalog-preparation/behavior.yaml`, `artifacts/wire_contracts.yaml`, `artifacts/data-model.md`
- **Description**: Extend source preparation to parse the supplied official ICD-10-CM tabular XML and applicable index/neoplasm/drug files, preserving code hierarchy, billable status, inclusion/exclusion notes, sequencing notes, code-first/use-additional-code instructions, effective year, and source location. Validate against the supplied schema and retain the existing code-description catalog.

- [ ] T012 [Plan:7] Parse the supplied ICD-10-CM tabular XML and relevant index/addenda into versioned records in `scripts/prepare_data.py` and `data/coding/ICD10CM/`.
- [ ] T013 [Plan:7] Add schema, hierarchy, instruction, effective-year, and source-location validation tests in `tests/test_medicoders.py`.

#### Step 8: Add HCPCS recommendation validation
- **Requirements**: REQ-010
- **Design inputs**: `artifacts/units/catalog-preparation/behavior.yaml`, `artifacts/units/clinical-analysis/behavior.yaml`
- **Description**: Add rule checks for applicable HCPCS category/code metadata, effective dates, modifiers/coverage constraints present in licensed reference material, and consistency with documented services. Return explicit validation evidence and coder-review flags; do not infer coverage or medical necessity from a text match.

- [ ] T014 [Plan:8] Implement HCPCS applicability and source-backed rule validation in `backend/services/coding/hcpcs_validation.py`.
- [ ] T015 [Plan:8] Add supported/unsupported/effective-date/modifier validation tests in `tests/test_medicoders.py`; assert unavailable source rules become review flags rather than inferred coverage.

#### Step 9: Add local embeddings and persistent vector indexing
- **Requirements**: REQ-004
- **Design inputs**: `artifacts/units/clinical-analysis/unit_decomposition.yaml`; `research.md`
- **Description**: Implement local embedding generation and a local persistent vector-store adapter. Index versioned code descriptions and tabular instructions with stable source identifiers; support atomic rebuilds, version mismatch detection, and index integrity checks.

- [ ] T016 [Plan:9] Implement local vector-store persistence and atomic versioned index builds in `backend/services/retrieval/vector_store.py`.
- [ ] T017 [Plan:9] Add offline persistence, rebuild, version mismatch, and index-integrity tests in `tests/test_medicoders.py`.

#### Step 10: Implement provenance-preserving RAG retrieval
- **Requirements**: REQ-003, REQ-004, REQ-009, REQ-010
- **Design inputs**: `artifacts/wire_contracts.yaml`, `artifacts/units/clinical-analysis/behavior.yaml`
- **Description**: Combine lexical and semantic retrieval over the locally indexed, effective coding references. Return the retrieved text, code/catalog year, source file/location, and retrieval score; require a downstream validation step and retain deterministic search as a debuggable fallback.

- [ ] T018 [Plan:10] Implement hybrid lexical/semantic retrieval and source-linked result records in `backend/services/retrieval/rag.py`.
- [ ] T019 [Plan:10] Add retrieval relevance, provenance, effective-year, and deterministic-fallback tests in `tests/test_medicoders.py`.

### Phase 4: Orchestrated coder-assistance workflow

#### Step 11: Orchestrate the workflow with LangGraph
- **Requirements**: REQ-001, REQ-002, REQ-003, REQ-005, REQ-009, REQ-010
- **Design inputs**: `artifacts/units/clinical-analysis/unit_decomposition.yaml`, `artifacts/units/api-workflows/behavior.yaml`, `artifacts/wire_contracts.yaml`
- **Description**: Add explicit graph state and nodes for parsing, context extraction, retrieval, local LLM candidate reasoning, code-rule validation, uncertainty handling, explanation, and human review. Add bounded retries/timeouts and observable node errors. The graph must not approve or finalize a code.

- [ ] T020 [Plan:11] Implement LangGraph nodes, typed state transitions, and candidate-to-validation handoff in `backend/services/workflow/graph.py`.
- [ ] T021 [Plan:11] Add graph timeout, unavailable-model, retrieval failure, abstention, and human-review path tests in `tests/test_medicoders.py`.

#### Step 12: Surface evidence, uncertainty, and review states
- **Requirements**: REQ-001, REQ-002, REQ-003, REQ-005, REQ-009, REQ-010
- **Design inputs**: `artifacts/units/web-client/behavior.yaml`, `artifacts/wire_contracts.yaml`
- **Description**: Update result/review UI and API response schema to show clinical evidence spans, retrieved instructions, catalog year/source, validation results, uncertainty/abstention, and model provenance. Preserve case ownership and existing coder decision controls.

- [ ] T022 [Plan:12] Extend analysis response serialization and account-scoped case storage in `backend/schemas.py` and `backend/main.py` for evidence, sources, model/version, and validation status.
- [ ] T023 [Plan:12] Render citations, uncertainty, and review flags in `frontend/index.html`, `frontend/app.js`, and `frontend/styles.css`; add a browser-flow check for coder decisions.

### Phase 5: Evaluation and release gating

#### Step 13: Add model and retrieval evaluation metrics
- **Requirements**: REQ-011
- **Design inputs**: `research.md`, `artifacts/units/clinical-analysis/behavior.yaml`
- **Description**: Implement a versioned offline evaluation runner with reproducible data/model/index versions. Measure extraction span/category precision/recall/F1, retrieval recall@k/ranking, graph completion/error/abstention rates, latency, and resource use; compare results to the existing deterministic baseline.

- [ ] T024 [Plan:13] Add an offline evaluation runner and machine-readable metric report in `backend/services/evaluation/` and `scripts/evaluate_pipeline.py`.

#### Step 14: Evaluate coding accuracy on adjudicated cases
- **Requirements**: REQ-012
- **Design inputs**: `research.md`, `artifacts/data-model.md`
- **Description**: Define a coder-reviewed reference set with coding year, documentation evidence, accepted codes, and adjudication metadata. Measure exact/partial code agreement, precision/recall/F1, unsupported-code rate, critical sequencing/instruction violations, and reviewer override rate by code family and documentation context. Do not treat Synthea condition labels as gold-standard ICD coding.

- [ ] T025 [Plan:14] Add adjudicated-case evaluation schemas and coding accuracy metrics in `backend/services/evaluation/coding_accuracy.py`; require explicit dataset version and reviewer provenance.

#### Step 15: Enforce non-PHI release gates and approval evidence
- **Requirements**: REQ-011, REQ-012
- **Design inputs**: `research.md`, `artifacts/wire_contracts.yaml`
- **Description**: Require reproducible evaluation results, security/privacy review, local inference/network verification, backup/retention/access-control review, clinician sign-off, and organizational legal/regulatory approval before enabling real-data use. Until these approvals exist, deployment remains synthetic/de-identified engineering or demo use only.

- [ ] T026 [Plan:15] Add a release checklist and deployment-mode enforcement in `README.md`, `backend/config.py`, and `compose.yaml`; keep real-data mode disabled until recorded organizational approval and required evaluation gates are satisfied.

## Project Structure

```text
backend/
  services/
    ingestion/       # bounded text/PDF/DOCX extraction and evidence offsets
    clinical_nlp/    # context-aware extraction and schemas
    coding/          # ICD/HCPCS rule validation
    retrieval/       # local embeddings, index, and provenance-aware RAG
    workflow/        # LangGraph state and nodes
    evaluation/      # offline metrics and reproducible reports
  main.py            # existing FastAPI routes, adapted to new services
scripts/
  prepare_data.py    # versioned ICD tabular and HCPCS import
  import_synthea.py  # complete synthetic test corpus import
  evaluate_pipeline.py
tests/
  unit/
  integration/
  fixtures/
data/
  coding/            # licensed/versioned coding references
  evaluation/        # approved synthetic/de-identified labeled fixtures only
```

## Testing Strategy

- **appType**: Mixed (FastAPI API plus static browser SPA and local model/index services).
- **Critical user journeys**:
  1. Upload PDF/DOCX; malformed/oversized input returns an explicit error, valid input preserves evidence offsets.
  2. Analyze text with negated, historical, uncertain, and active conditions; review structured extraction and citations.
  3. Retrieve an ICD-10-CM code and its tabular instructions for the correct effective year.
  4. Validate an HCPCS suggestion against available reference constraints and surface unsupported assumptions for review.
  5. Run the full synthetic import and reproducible evaluation; verify the coder must make the final decision.
- **primaryValidationStack**: pytest, FastAPI TestClient, local model runtime and local vector store; browser-level tests for review/evidence flows.
- **fallbackMatrix**:
  - `infra-tier`: local model server + persistent local vector store → deterministic fake model and temporary local index for unit/integration tests. Fallback does not prove model quality or production resource capacity.
  - `browser-tier`: browser automation when available → API/TestClient and DOM/static checks. API fallback does not prove visual/accessibility behavior.
- **Environment requirements**: Python environment; actual local model and intended CPU/GPU/memory profile for performance/quality benchmark; local vector-store persistence; Docker for deployment verification; approved synthetic/curated test data.
- **knownGaps**: synthetic-only test runs do not establish clinical coding accuracy; a mocked model does not validate prompt/model performance; no HIPAA or regulatory readiness can be inferred from software tests.
- **Test data strategy**: deterministic synthetic fixtures with generated IDs; keep synthetic Synthea data isolated; use adjudicated de-identified cases only after organizational approval; version every dataset/model/index and clean temporary DB/index between tests.
- **Acceptance criteria**: PDF and DOCX ingestion reports parse errors and preserves source locations; model and vector access are local with no external fallback; every recommendation has source evidence and effective code-set version; unsupported/ambiguous cases abstain or require human review; no auto-validation; full synthetic import is repeatable; evaluation metrics are reproducible; real-data use remains disabled pending signed approval.
- **Validation review expectations**: confirm requirement-to-task traceability, API/account-isolation compatibility, source provenance, error transparency, evaluation methodology, privacy constraints, and no claim that synthetic performance equals clinical validity.

## Requirement Mapping

| REQ ID | Description | Plan Items | Implementation Evidence |
|---|---|---|---|
| REQ-001 | Integrate a locally hosted LLM for coding assistance | 1.1, 1.2, 3.4, 4.1, 4.2 | `backend/services/llm/`, workflow services, model configuration, evidence UI |
| REQ-002 | Implement explicit LangGraph multi-agent/workflow execution | 1.3, 4.1, 4.2 | `backend/services/workflow/`, graph state/nodes, workflow tests |
| REQ-003 | Implement provenance-preserving local RAG | 3.4, 4.1, 4.2 | `backend/services/retrieval/`, source-linked recommendations, retrieval tests |
| REQ-004 | Add local embeddings and persistent vector database | 1.2, 3.3, 3.4 | embedding/vector adapters, local index files, offline rebuild/integrity tests |
| REQ-005 | Improve clinical NLP for context, history, negation, and uncertainty | 1.3, 2.2, 4.1 | `backend/services/clinical_nlp/`, structured extraction/evidence tests |
| REQ-006 | Accept and safely parse PDF uploads | 4 | PDF parser, upload validation, evidence-offset tests |
| REQ-007 | Accept and safely parse DOCX uploads | 4 | DOCX parser, upload validation, evidence-offset tests |
| REQ-008 | Import the full Synthea corpus for isolated testing | 6 | `scripts/import_synthea.py`, synthetic fixture store, import consistency tests |
| REQ-009 | Integrate ICD-10-CM tabular hierarchy and coding instructions | 7, 9, 10, 11 | versioned tabular catalog, XML importer, instruction/provenance tests |
| REQ-010 | Validate HCPCS suggestions against applicable reference rules | 8, 10, 11 | HCPCS rule service, source-linked validation results, rule tests |
| REQ-011 | Add reproducible model/retrieval/workflow evaluation metrics | 1.1, 1.2, 6, 13, 15 | `backend/services/evaluation/`, reports, regression and reproducibility tests |
| REQ-012 | Evaluate coding accuracy against coder-adjudicated cases | 1.1, 14, 15 | versioned adjudicated evaluation set/process, accuracy and safety metrics, approval evidence |
