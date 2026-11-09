# MediBridge Architecture Index

## Implementation Guide

This index describes the existing prototype and gives navigation to its evidence artifacts. **This index is not the full contract. Do not implement from this file alone; follow the artifact paths below.**

### Global artifacts

- `unit_graph.yaml` — route/CLI/UI entry points, dependencies, and shared references.
- `wire_contracts.yaml` — API and source-file contracts; rows identify their owning unit.
- `shared_modules.yaml` — shared database and clinical-analysis modules; filter `used_by_units`.
- `cross_unit_state.yaml` — implicit session-cookie flow; filter by writer/reader unit.
- `project-structure.md`, `tech-stack.md`, `data-model.md` — current architecture, dependencies, and persisted entities.

### Unit: api-workflows

- Trigger: authenticated REST routes under `/api/*`, health route, and static-page fallback.
- Read `units/api-workflows/behavior.yaml` and `units/api-workflows/bindings.yaml`.
- Filter `wire_contracts.yaml` by `unit: api-workflows`; read shared modules by `used_by_units`.
- Before completion report: changed API behavior, preserved account scoping/error shapes, and test evidence.

### Unit: clinical-analysis

- Trigger: `analyze_text()` calls from API and demo seeding.
- Read `units/clinical-analysis/behavior.yaml` and `units/clinical-analysis/bindings.yaml`.
- Filter shared modules by `used_by_units`; review clinical-analysis-service split candidates as advisory.
- Before completion report: extraction, evidence, retrieval, validation, and human-review behavior plus evaluation evidence.

### Unit: web-client

- Trigger: browser SPA pages and user interactions.
- Read `units/web-client/behavior.yaml` and `units/web-client/bindings.yaml`.
- Filter `cross_unit_state.yaml` where writer or reader is `web-client`.
- Before completion report: rendered states, error handling, accessibility, and browser validation evidence.

### Unit: catalog-preparation

- Trigger: `python scripts/prepare_data.py <source-folder>`.
- Read `units/catalog-preparation/behavior.yaml` and `units/catalog-preparation/bindings.yaml`.
- Filter `wire_contracts.yaml` by `unit: catalog-preparation`.
- Before completion report: accepted source versions, deterministic output, validation failures, and import test evidence.

### Unit: synthea-demo-seeding

- Trigger: `python scripts/seed_synthea_demo.py <csv-folder>`.
- Read `units/synthea-demo-seeding/behavior.yaml` and `units/synthea-demo-seeding/bindings.yaml`.
- Filter shared modules by `used_by_units`; filter wire contracts by `unit`.
- Before completion report: imported synthetic fields, account isolation, idempotency behavior, and test evidence.
