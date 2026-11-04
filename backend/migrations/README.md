# Cicero Alembic setup

This directory configures Alembic for the existing multi-schema PostgreSQL database.

## Safety status

This is configuration only. It does **not** create a migration revision, stamp the
database, run `upgrade`, or modify Cloud SQL.

## Managed schemas

Application autogeneration is limited to:

- `auth`
- `cases`
- `documents`
- `intelligence`
- `research`
- `agents`
- `evidence`
- `memory`

The `public.alembic_version` table is reserved for Alembic bookkeeping and is
excluded from application metadata comparisons.

## Connection modes

1. **Preferred Cloud SQL mode:** a future runner should obtain a connection from
   the existing `DatabaseManager` (therefore preserving Cloud SQL Connector and
   Modal Workload Identity Federation), then provide its synchronous SQLAlchemy
   connection through `alembic_cfg.attributes["connection"]`.
2. **Local direct mode:** set `CICERO_ALEMBIC_DATABASE_URL` to a PostgreSQL
   asyncpg URL. Do not commit that URL or place credentials in source control.

Do not use the placeholder URL in `alembic.ini` to connect.

## Next steps

1. Verify that Alembic imports all 11 ORM tables.
2. Connect read-only to Cloud SQL and produce a schema parity report.
3. Resolve every unexpected difference before generating a baseline revision.
4. Only after parity is clean, create an empty baseline revision and stamp the
   existing database. Do not run DDL against the existing tables as a baseline.
