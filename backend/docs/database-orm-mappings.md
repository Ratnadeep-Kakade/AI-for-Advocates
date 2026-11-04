# Milestone 3.2.2 — Existing database ORM mappings

The package `cicero.db.models` maps the 11 tables currently present in the
`auth`, `cases`, and `documents` schemas.

## Importing metadata

Import `cicero.db.models` before inspecting `Base.metadata`. The package
initializer imports each model module so all 11 tables are registered.

```python
from cicero.db.base import Base
import cicero.db.models  # registers mappings

metadata = Base.metadata
```

## Scope and safety

- These are declarative mappings of the existing Cloud SQL schema.
- The mappings preserve existing UUID keys, server defaults, composite
  foreign keys, unique constraints, check constraints, and indexes.
- PostgreSQL `TIMESTAMP` columns are mapped as timezone-naive `DateTime`.
- JSONB columns remain PostgreSQL JSONB.
- No vector, full-text-search, or parent-child chunk fields have been added.
- No call to `Base.metadata.create_all()` is made.
- No database DDL or data changes are performed by importing these models.

The empty `intelligence`, `research`, `agents`, `evidence`, and `memory`
schemas are intentionally not mapped because they contain no tables yet.

## Validation

`tests/test_orm_mappings.py` checks that all 11 existing tables register and
that key document/organization relationships and chunk fields are retained.

Run:

```powershell
uv run pytest tests/test_orm_mappings.py
```

Full database reflection parity and Alembic configuration are separate
follow-up work in Milestone 3.2.4. Do not stamp or apply a migration until
that parity check has been completed.
