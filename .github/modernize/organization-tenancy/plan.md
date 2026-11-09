# Implementation Plan: MediBridge Organization Tenancy and PostgreSQL

**Project**: MediBridge  
**Status**: Planning only — no application changes or plan tasks have been run.

## Technical Context

- **Language/runtime**: Python (README specifies Python 3.10+)
- **Framework**: FastAPI
- **Current persistence**: SQLite via direct `sqlite3` calls in `backend/database.py`
- **Current tests**: pytest and FastAPI `TestClient`
- **Existing behavior to preserve**: clinical NLP/context extraction, LangGraph
  workflow, ICD-10-CM/HCPCS catalogs, retrieval/RAG, ingestion, evaluation,
  coder review, and synthetic-only research/demo workflow.

## Overview

Extend the existing application—not rebuild it—with organization-scoped
accounts and case access, administrative onboarding and account controls,
hospital assignment, and PostgreSQL persistence managed through SQLAlchemy
and Alembic. Deliver the work as small, sequential changes with focused tests
at each stage, followed by regression tests and updated documentation.

Clinical analysis must remain disabled unless the existing release-evidence
gate passes. This plan does not establish clinical readiness, validate
security, or authorize PHI use.

## Scope and guardrails

- Add organizations, memberships, roles, invitations, lifecycle controls,
  account recovery, MFA, and hospital case assignment/access rules.
- Separate research/demo pathways from hospital/clinical pathways and preserve
  the current release-approval gate.
- Migrate the persistence layer to SQLAlchemy/Alembic and PostgreSQL without
  deleting or silently rewriting any existing database or data.
- Keep all listed clinical analysis, retrieval, ingestion, coding-catalog,
  evaluation, and human-review capabilities intact.
- Existing repository paths include `database/medibridge.db`,
  `data/synthea-demo.sqlite`, and a local retrieval index. Treat each as
  user data; do not remove, overwrite, or repurpose them. Clinical catalogs
  and research/demo data are not part of the application-database migration.
- Keep deployment/production data migration separate from schema development;
  require a tested backup, explicit source-to-organization mapping, and
  operator approval before applying any migration to existing user data.

## High-level delivery sequence

1. Establish current behavior and data-preservation test coverage.
2. Introduce the PostgreSQL-capable persistence and migration foundation.
3. Implement tenant identity, authorization, onboarding, lifecycle, and
   hospital/research access boundaries.
4. Verify assignment and authentication behavior with focused and
   cross-tenant tests.
5. Update operator/developer documentation and reconcile package manifests.

Each stage is gated by targeted tests before the next stage begins. Detailed
task boundaries, affected areas, dependencies, and acceptance criteria are in
`.metadata/tasks.json`.

## Data migration and unresolved decisions

The workspace currently contains `database/medibridge.db`, despite prior
context stating the database had been removed. This plan preserves it and
does not infer permission to migrate, delete, or modify it. Before a live data
migration, confirm whether that database is in scope and how each existing
user, case, and activity record should map to an organization. Records without
an approved mapping must not become visible across tenants.

Other decisions needed before implementation are the PostgreSQL deployment
target/version, the approved email-delivery mechanism for invitations and
password recovery, and the MFA factor/policy. The implementation team should
confirm those choices before enabling external delivery or choosing
organization-wide policy defaults.

## Open Questions

- [ ] Is the currently present `database/medibridge.db` the database mentioned
  as previously removed, and is it in scope for a later data migration?
- [ ] What organization should own each existing account/case/activity record?
  No default organization or cross-tenant visibility is assumed.
- [ ] What PostgreSQL version/hosting target is intended?
- [ ] Which email provider or delivery adapter should send invitations and
  password-recovery links?
- [ ] Which MFA factor and enforcement policy should be used (for example,
  TOTP, and whether it is optional or mandatory by role)?
- [ ] What exact roles and access rules distinguish research users from
  hospital users, and who may administer each organization?

## Acceptance and non-claims

The plan is complete when the task acceptance criteria pass, existing approved
features remain regression-tested, and no existing data is deleted or
silently reassigned. Security controls still require independent review.
Passing engineering tests does not establish security validation, clinical
accuracy, regulatory compliance, or readiness for real clinical use.
