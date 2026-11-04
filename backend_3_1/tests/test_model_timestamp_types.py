"""Regression tests for timezone-aware timestamps in existing ORM mappings."""

import cicero.db.models  # noqa: F401
from sqlalchemy import DateTime

from cicero.db.base import Base


EXPECTED_TIMEZONE_AWARE_COLUMNS = {
    "auth.organization_members.joined_at",
    "auth.organizations.created_at",
    "auth.organizations.updated_at",
    "auth.users.created_at",
    "auth.users.updated_at",
    "cases.case_members.assigned_at",
    "cases.case_parties.created_at",
    "cases.cases.created_at",
    "cases.cases.updated_at",
    "documents.document_chunks.created_at",
    "documents.document_extractions.created_at",
    "documents.document_processing_runs.started_at",
    "documents.document_processing_runs.completed_at",
    "documents.document_processing_runs.created_at",
    "documents.document_versions.created_at",
    "documents.documents.created_at",
    "documents.documents.updated_at",
}


def test_existing_timestamp_columns_are_timezone_aware():
    actual = set()

    for table in Base.metadata.tables.values():
        for column in table.columns:
            if isinstance(column.type, DateTime):
                assert column.type.timezone is True, (
                    f"{table.schema}.{table.name}.{column.name} "
                    "must use a timezone-aware timestamp"
                )
                actual.add(f"{table.schema}.{table.name}.{column.name}")

    assert actual == EXPECTED_TIMEZONE_AWARE_COLUMNS
