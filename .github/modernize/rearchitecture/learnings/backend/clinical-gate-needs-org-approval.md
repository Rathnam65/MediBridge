# Clinical Gate Needs Organization Approval

Release evidence alone must not enable clinical processing when the organization approval boundary is not implemented or enforceable.

## What Happened

In MediBridge's organization-tenancy execution, the existing release-evidence check could return enabled without any organization membership or approval model. Until tenancy authorization exists, settings now keep clinical processing disabled and report the missing organization-scoped approval control.

## Takeaway

When an approval prerequisite cannot be evaluated at the correct organization boundary, fail closed instead of adding a global flag that could be mistaken for organization authorization. Restore enablement only after membership, role, organization approval, and existing release evidence are enforced together at the analysis boundary.

## History
- 2026-11-09 (MediBridge/organization-tenancy-safe-foundation): initial
