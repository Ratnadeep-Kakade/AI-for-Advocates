"""Baseline for the existing Cicero database schema.

This revision intentionally contains no application-schema DDL. It is applied
with ``alembic stamp`` to mark the already-existing schema as the migration
starting point.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20261104_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """The existing schema is adopted via stamp; do not recreate it."""
    pass


def downgrade() -> None:
    """The baseline has no reversible application-schema operations."""
    pass
