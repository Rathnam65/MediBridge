## [organization-tenancy-safe-foundation] Isolated tests and fail-closed data safety
- Codebase/domain discoveries: `backend.main` calls `init_db()` during module import, so ordinary pytest fixtures run too late to protect the default database path; the test `conftest.py` must set isolated paths before test-module imports. `init_db` also had an ambiguous legacy-settings branch that dropped `settings` when `legacy_settings` already existed.
- Wrong assumptions and corrections: the repository has no `.git` metadata, despite being a workspace called MediBridge; no Git diff/status can be used as evidence. SQLAlchemy and Alembic are not installed, and no PostgreSQL runtime was verified.
- Debugging dead-ends and what actually worked: test execution was safe after setting database and retrieval paths in `tests/conftest.py`; metadata-only checks before and after the suite showed all three resident SQLite files unchanged.
- Techniques/patterns worth reusing: perform persistence characterization against temporary synthetic databases, reject ambiguous migrations before any DDL, and keep clinical analysis blocked until organization-scoped approval is enforceable.
- Learnings consumed: []
