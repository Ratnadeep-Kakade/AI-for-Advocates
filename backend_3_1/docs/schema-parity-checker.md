# Read-only database schema parity check

The checker compares the live PostgreSQL schema with Cicero's SQLAlchemy ORM
metadata. It covers the eight existing Cicero schemas and all mapped tables.
It reports schema/table/column presence, PostgreSQL types, nullability, server
defaults, primary keys, foreign keys, unique constraints, check constraints and
standalone indexes (including expression indexes).

## Run against the existing Cloud SQL instance

From the backend project root:

```powershell
uv run modal run scripts/check_schema_parity.py::check_schema_parity
```

The Modal function uses the existing `cicero-database` Secret, Cloud SQL Python
Connector and Workload Identity Federation configuration. Its deployed Modal
function name is intentionally `fastapi_app`, matching the existing Google
Workload Identity Provider attribute condition.

## Safety properties

- The function opens a PostgreSQL transaction and executes `SET TRANSACTION
  READ ONLY` before schema inspection.
- The checker uses SQLAlchemy Inspector/catalog reflection only.
- It does not create tables, alter columns, create indexes, generate Alembic
  revisions, stamp Alembic, or execute migrations.
- The report includes `"read_only": true`, a PASS/FAIL status, a summary and
  individual differences.

## Interpreting results

A PASS means the inspected structure matches the current ORM metadata for the
objects checked. A FAIL lists structural differences. Review every difference
before changing ORM metadata or writing a migration. PostgreSQL may render
semantically equivalent defaults and expressions differently, so the checker
normalizes a limited set of harmless formatting and text casts. It does not
silently ignore missing columns, unexpected columns, constraints or indexes.

The five currently empty schemas (`intelligence`, `research`, `agents`,
`evidence`, `memory`) are checked for existence and for unexpected tables, even
though they have no ORM tables yet.
