# Milestone 3.2.4.1: Alembic foundation

## What this slice adds

- Alembic dependency.
- Multi-schema migration configuration.
- ORM metadata registration for all existing tables.
- Filters restricting autogeneration to Cicero's eight schemas.
- Alembic version bookkeeping in `public.alembic_version`.
- Support for a caller-supplied SQLAlchemy connection, so production migrations
  can reuse `DatabaseManager` and Cloud SQL Connector/WIF.
- Local direct-URL mode for development only.

## What it intentionally does not do

- No revision is generated.
- No baseline is created.
- No database is stamped.
- No `upgrade` or `downgrade` is executed.
- No DDL is sent to Cloud SQL.

## Local commands after installing the updated lockfile

```powershell
uv sync
uv run alembic --version
uv run pytest
```

Do not run `alembic revision --autogenerate` or `alembic upgrade head` yet.
The next slice will implement a read-only live schema parity report first.
