# Existing Data Model

Persistence is implemented directly in `backend/database.py` with SQLite DDL and startup-time additive migrations. There is no ORM.

## Entities

- **users**: `id` primary key, unique case-insensitive `email`, `full_name`, `password_hash`, and `created_at`.
- **auth_sessions**: token hash primary key, user foreign key with cascade delete, and Unix-time `expires_at`.
- **cases**: `id` primary key, optional user foreign key, creation/assignment/deadline timestamps, document name/source/text, status, numeric overall match score, and JSON text columns for extracted terms, recommendations, and gaps. User ownership is account-scoped by API queries. Legacy unowned cases may remain.
- **activity**: auto-increment integer key, optional user foreign key, timestamp, kind, title, and detail.
- **settings**: composite primary key `(user_id, key)`, user foreign key with cascade delete, and string value. Legacy global settings may be retained in `legacy_settings`.

## Relationships and transaction boundaries

- `users` 1-to-many `auth_sessions`, `cases`, `activity`, and `settings`; foreign keys are enabled on each SQLite connection.
- Signup writes a user and session in one connection/commit. Case analysis inserts the case separately from the activity write. User decisions update case status and then write activity.
- Database setup is idempotent and upgrades existing case/activity/settings schemas in `init_db()`.
- Coding catalogs are files in the repository/image, not database entities. Clinical analysis content and JSON results are stored directly in `cases`.

## Key entities

1. `users` — account identity and password hash.
2. `auth_sessions` — expiring authenticated browser sessions.
3. `cases` — uploaded/pasted clinical text, analysis output, status, and coder workload dates.
4. `activity` — account-scoped audit/workflow events.
5. `settings` — account-scoped workspace preferences.
6. `legacy_settings` — preserved settings from an older global-settings schema when present.
