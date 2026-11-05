from __future__ import annotations

from pathlib import Path

import cicero.db.models  # noqa: F401
from cicero.db.base import Base


def test_all_existing_tables_are_registered() -> None:
    expected = {
        ("auth", "users"),
        ("auth", "organizations"),
        ("auth", "organization_members"),
        ("cases", "cases"),
        ("cases", "case_members"),
        ("cases", "case_parties"),
        ("documents", "documents"),
        ("documents", "document_versions"),
        ("documents", "document_processing_runs"),
        ("documents", "document_extractions"),
        ("documents", "document_chunks"),
        ("agents", "executions"),
        ("agents", "execution_tasks"),
        ("agents", "agent_results"),
    }
    actual = {(table.schema, table.name) for table in Base.metadata.tables.values()}
    assert actual == expected


def test_migration_environment_declares_only_cicero_schemas() -> None:
    env_path = Path("migrations/env.py")
    source = env_path.read_text(encoding="utf-8")
    for schema in (
        "auth",
        "cases",
        "documents",
        "intelligence",
        "research",
        "agents",
        "evidence",
        "memory",
    ):
        assert f'"{schema}"' in source
    assert "include_schemas=True" in source
    assert "compare_type=True" in source


def test_migration_environment_has_no_automatic_schema_creation() -> None:
    source = Path("migrations/env.py").read_text(encoding="utf-8")
    assert "include_name=include_name" in source
    assert "include_object=include_object" in source
    assert "version_table_schema=VERSION_SCHEMA" in source
