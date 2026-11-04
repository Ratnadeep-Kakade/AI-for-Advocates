"""Baseline for the existing Cicero database schema.

This revision intentionally contains no application-schema DDL. It is applied
with ``alembic stamp`` to mark the already-existing schema as the migration
starting point.
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20261104_0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """The existing schema is adopted via stamp; do not recreate it."""
    pass


def downgrade() -> None:
    """The baseline has no reversible application-schema operations."""
    pass
