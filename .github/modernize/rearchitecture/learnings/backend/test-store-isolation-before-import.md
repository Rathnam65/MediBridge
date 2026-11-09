# Test Store Isolation Before Import

When application import initializes persistence, configure test database and retrieval paths before test-module collection rather than in normal fixtures.

## What Happened

In MediBridge's organization-tenancy execution, `backend.main` calls `init_db()` at import time. A fixture that runs later cannot prevent an import from opening the default repository database. Setting isolated `DATABASE_PATH` and `VECTOR_INDEX_PATH` values in `tests/conftest.py` ensures they are active before tests import the application.

## Takeaway

For applications with import-time initialization, establish disposable persistent-store paths in the earliest test bootstrap file and assert those resolved paths are outside the repository. Do not rely on per-test monkeypatches as the only guard.

## History
- 2026-11-09 (MediBridge/organization-tenancy-safe-foundation): initial
