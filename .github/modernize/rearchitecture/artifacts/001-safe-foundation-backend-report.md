# Organization Tenancy — Safe Foundation Execution

**Status:** Partial execution. The bounded preservation and fail-closed foundations below passed verification; the approved organization-tenancy plan is not complete.

## Summary

Executed the safe first-stage work from the approved plan and a narrow clinical-gate safeguard. Pytest now selects disposable database and retrieval paths before application imports; ambiguous legacy settings schemas cause startup refusal rather than a table drop; and clinical analysis remains disabled until organization-scoped approval enforcement exists. No tenant, account, assignment, or PostgreSQL migration features were delivered.

## Exact Changed Files

- `backend/config.py` — retain the release-evidence requirements and synthetic-demo exclusion, while fail-closing clinical analysis because no organization approval mechanism exists.
- `backend/database.py` — refuse initialization before schema changes when both an unscoped `settings` table and `legacy_settings` exist.
- `tests/conftest.py` — route database, retrieval index, and release-evidence paths to isolated temporary locations before importing the application.
- `tests/test_data_safety.py` — verify isolated paths, fail-closed test configuration, and preservation of both tables in a synthetic ambiguous-schema fixture.
- `tests/test_auth.py` — verify complete release evidence still cannot enable clinical analysis without organization approval.
- `tests/test_medicoders.py` — update release-gate characterization to assert the organization-approval fail-closed condition.

## Baseline

- Approved inputs read: `.github/modernize/organization-tenancy/plan.md` and `.github/modernize/organization-tenancy/.metadata/tasks.json`.
- Plan order is sequential: baseline/preservation → SQLAlchemy/Alembic/PostgreSQL foundation → tenancy/RBAC → invitations/lifecycle/recovery → MFA → research/hospital gates → case assignment → cross-cutting regressions → documentation.
- Initial project state: Python 3.13.7; FastAPI 0.141.1; pytest 9.1.1; SQLAlchemy and Alembic are not installed. Persistence remains direct `sqlite3`.
- The workspace has no Git repository metadata, so a Git status/diff baseline could not be collected.
- Data files were checked only for existence, size, and modification time; their contents were not read:
  - `database/medibridge.db`: 65,536 bytes; `2026-11-09T09:30:53.6772111Z`
  - `data/synthea-demo.sqlite`: 29,245,440 bytes; `2026-11-09T06:35:29.1201548Z`
  - `data/retrieval/medibridge.sqlite`: 120,868,864 bytes; `2026-11-09T06:39:59.1831075Z`

## Test Results

- Baseline command: `.\.venv\Scripts\python.exe -m pytest -q tests/test_auth.py::test_clinical_analysis_is_disabled_without_explicit_approval tests/test_auth.py::test_synthetic_production_mode_overrides_clinical_approval tests/test_auth.py::test_builtin_synthetic_examples_are_removed tests/test_auth.py::test_public_synthetic_inputs_are_ephemeral_and_require_confirmation`
  - Passed: 4; failed: 0; skipped: 0; warning: 1 deprecation warning.
- Targeted command after the final gate and safety changes: `.\.venv\Scripts\python.exe -m pytest -q tests/test_data_safety.py tests/test_auth.py::test_clinical_analysis_is_disabled_without_explicit_approval tests/test_auth.py::test_complete_release_evidence_still_cannot_bypass_missing_org_approval tests/test_auth.py::test_synthetic_production_mode_overrides_clinical_approval tests/test_auth.py::test_public_synthetic_inputs_are_ephemeral_and_require_confirmation tests/test_medicoders.py::test_release_gate_requires_every_referenced_approval_and_opt_in`
  - Passed: 8; failed: 0; skipped: 0; warning: 1 deprecation warning.
- Full regression command: `.\.venv\Scripts\python.exe -m pytest -q`
  - Passed: 38; failed: 0; skipped: 0; warnings: 2 deprecation warnings (Starlette `BlockingPortal` alias and Python SQLite datetime adapter).
- API contract-script discovery: no `api-test.sh`, `api-check.sh`, `smoke.sh`, `health-check.sh`, or `test-api.sh` was present.
- Runtime command: `.\.venv\Scripts\python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8765`, with database and retrieval paths set to a disposable temporary directory and release evidence unavailable.
  - `GET /api/health`: 200; clinical disabled and gate reasons include missing release evidence and missing organization-scoped approval enforcement.
  - `GET /api/demo/config`: 200; demo disabled in this runtime.
  - `GET /api/auth/me`: 200; `{"user":null}`.
- Repository data metadata after all checks exactly matched the recorded baseline above.

## Data Safety

- No application, synthetic-demo, or retrieval-index database contents were inspected.
- No existing database was opened by the test or runtime commands. All test/runtime database and retrieval paths were redirected to temporary locations.
- No existing database was deleted, overwritten, reset, migrated, or reassigned. No clinical catalog, synthetic-data, or retrieval-index file was changed.
- The new ambiguous-settings test uses only a newly created synthetic database under pytest's temporary directory.

## Evidence Mapping

- `tasks.json#001-baseline-and-preservation-tests` → isolated store setup, isolated-path assertions, synthetic-only non-persistence coverage, and baseline/full-suite test evidence above.
- `tasks.json#006-research-and-hospital-access-gates` → `backend/config.py` fails closed until organization approvals can be enforced; the complete-release-evidence route test confirms `/api/analyze/text` returns 503 and persists no case.
- `plan.md#Scope and guardrails` → repository database, synthetic database, and retrieval-index metadata remained unchanged; no live migration or implicit organization mapping was attempted.

## Remaining Work and Limitations

- Task 002 is not implemented: no SQLAlchemy/Alembic persistence foundation, initial migration, PostgreSQL runtime, or PostgreSQL integration path.
- Tasks 003–005 are not implemented: organizations, memberships/RBAC, invitation and account lifecycle, password recovery, MFA, and session revocation remain absent.
- Task 006 is only fail-closed at the clinical gate. There is no research-versus-hospital authorization model or organization approval workflow.
- Task 007 is not implemented: hospital case assignment, reassignment, and organization-scoped queues are absent.
- Task 008 cross-organization/PostgreSQL regression tests and task 009 operations/developer documentation remain.
- Legacy user/case/activity ownership mapping, PostgreSQL target, invitation/recovery delivery provider, and MFA factor/policy remain unresolved in the approved plan.
- `backend/database.py` still contains automatic additive schema alterations and a legacy settings rename for other startup cases. They were not exercised against the resident database. Do not start the application against existing user data as a migration strategy; a separately approved, backed-up, tested migration process is still required.
- Clinical processing is deliberately disabled in application settings even when all release evidence is present, because organization-scoped approvals cannot yet be enforced. This is not a clinical-readiness, security, or compliance claim.

## Upstream Artifacts Consumed

- `.github/modernize/organization-tenancy/plan.md` — scope, preservation guardrails, sequencing, and unresolved decisions.
- `.github/modernize/organization-tenancy/.metadata/tasks.json` — acceptance requirements for tasks 001 and 006 and dependencies/order for remaining tasks.
- No separate dependency artifacts were provided.
