from cicero.db.base import Base
import cicero.db.models  # noqa: F401 - registers all mapped tables


def test_all_existing_tables_are_mapped() -> None:
    assert set(Base.metadata.tables) == {
        "auth.users",
        "auth.organizations",
        "auth.organization_members",
        "cases.cases",
        "cases.case_members",
        "cases.case_parties",
        "documents.documents",
        "documents.document_versions",
        "documents.document_processing_runs",
        "documents.document_extractions",
        "documents.document_chunks",
    }


def test_all_mapped_tables_have_primary_keys() -> None:
    assert len(Base.metadata.tables) == 11
    assert all(table.primary_key.columns for table in Base.metadata.tables.values())


def test_organization_scoping_is_preserved_in_document_mappings() -> None:
    documents = Base.metadata.tables["documents.documents"]
    versions = Base.metadata.tables["documents.document_versions"]
    assert {"document_id", "organization_id"} <= set(documents.columns.keys())
    assert any(
        tuple(column.name for column in constraint.columns)
        == ("document_id", "organization_id")
        for constraint in documents.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    )
    assert any(
        tuple(column.name for column in constraint.columns)
        == ("document_id", "organization_id")
        for constraint in versions.foreign_key_constraints
    )


def test_document_chunk_mapping_keeps_existing_fields() -> None:
    chunks = Base.metadata.tables["documents.document_chunks"]
    expected = {
        "chunk_id", "extraction_id", "version_id", "document_id",
        "organization_id", "chunk_index", "page_start", "page_end",
        "start_char", "end_char", "content", "token_count",
        "chunking_version", "created_at",
    }
    assert set(chunks.columns.keys()) == expected
