# Cicero Alembic baseline patch

## Contents

- `migrations/versions/20261104_0001_existing_schema_baseline.py`
  - Empty baseline revision. It contains no application-schema DDL.
- `scripts/stamp_alembic_baseline.py`
  - Modal task using the existing `DatabaseManager` and Modal WIF credentials.
  - Refuses to proceed if the connected database name differs from settings.
  - Refuses to proceed if `public.alembic_version` already exists.
  - Calls `alembic stamp`, then verifies the recorded revision.
  - Installs Alembic in the Modal image and uploads `alembic.ini` plus `migrations/`.

## Apply

Extract this ZIP into the existing `backend_3_1` directory, preserving paths.
Do not overwrite `migrations/env.py` or `alembic.ini`; this patch does not include
either file because the uploaded versions already provide the required
connection-injection and schema filtering behavior.

Run local tests:

```powershell
uv run pytest
```

Then run the Modal baseline stamp from the backend root:

```powershell
uv run modal run scripts/stamp_alembic_baseline.py::stamp_alembic_baseline
```

Expected success response includes:

- `status`: `SUCCESS`
- `version_table`: `public.alembic_version`
- `revision`: `20261104_0001`
- `application_tables_modified`: `false`

## Exact database effect

The operation creates `public.alembic_version` and inserts one revision row.
It does not execute the baseline revision's `upgrade()` function and does not
create, alter, or drop Cicero application tables.

If the version table already exists, the script stops rather than overwriting
or adopting unknown migration history.
