from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from cicero.db.models.documents import Document, DocumentVersion
from cicero.db.repositories import DocumentRepository


def _session_with_result(result: object) -> AsyncMock:
    session = AsyncMock()
    session.execute = AsyncMock(return_value=result)
    return session


@pytest.mark.asyncio
async def test_document_lookup_requires_organization_scope() -> None:
    document_id, organization_id = uuid4(), uuid4()
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    assert await DocumentRepository(session).get_by_id(
        document_id, organization_id=organization_id
    ) is None

    compiled = session.execute.await_args.args[0].compile(
        dialect=postgresql.dialect()
    )
    sql = str(compiled)
    assert "documents.documents.document_id" in sql
    assert "documents.documents.organization_id" in sql
    assert document_id in compiled.params.values()
    assert organization_id in compiled.params.values()


@pytest.mark.asyncio
async def test_list_by_case_scopes_by_case_and_organization_and_status() -> None:
    case_id, organization_id = uuid4(), uuid4()
    result = SimpleNamespace(
        scalars=MagicMock(return_value=SimpleNamespace(all=MagicMock(return_value=[])))
    )
    session = _session_with_result(result)

    assert await DocumentRepository(session).list_by_case(
        case_id, organization_id, status="active", limit=20, offset=10
    ) == []

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "documents.documents.case_id" in sql
    assert "documents.documents.organization_id" in sql
    assert "documents.documents.status" in sql
    assert case_id in compiled.params.values()
    assert organization_id in compiled.params.values()
    assert "active" in compiled.params.values()
    assert "LIMIT" in sql
    assert "OFFSET" in sql


@pytest.mark.asyncio
async def test_list_by_case_rejects_invalid_pagination() -> None:
    repository = DocumentRepository(AsyncMock())
    with pytest.raises(ValueError, match="limit"):
        await repository.list_by_case(uuid4(), uuid4(), limit=0)
    with pytest.raises(ValueError, match="offset"):
        await repository.list_by_case(uuid4(), uuid4(), offset=-1)


def test_create_document_stages_insert_without_commit() -> None:
    session = MagicMock()
    case_id, organization_id, uploaded_by = uuid4(), uuid4(), uuid4()

    document = DocumentRepository(session).create_document(
        case_id=case_id,
        organization_id=organization_id,
        uploaded_by=uploaded_by,
        title="  Contract  ",
        document_type="agreement",
    )

    assert isinstance(document, Document)
    assert document.case_id == case_id
    assert document.organization_id == organization_id
    assert document.uploaded_by == uploaded_by
    assert document.title == "Contract"
    session.add.assert_called_once_with(document)
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_update_details_is_organization_scoped_and_can_clear_document_type() -> None:
    document_id, organization_id = uuid4(), uuid4()
    document = Document(
        document_id=document_id,
        case_id=uuid4(),
        organization_id=organization_id,
        uploaded_by=uuid4(),
        title="Old title",
        document_type="agreement",
    )
    repository = DocumentRepository(AsyncMock())
    repository.get_by_id = AsyncMock(return_value=document)

    updated = await repository.update_details(
        document_id,
        organization_id,
        title="  New title ",
        document_type=None,
    )

    assert updated is document
    assert document.title == "New title"
    assert document.document_type is None
    assert document.updated_at is not None
    assert document.updated_at.tzinfo is None
    repository.get_by_id.assert_awaited_once_with(
        document_id, organization_id=organization_id
    )


@pytest.mark.asyncio
async def test_soft_delete_marks_record_without_deleting_or_committing() -> None:
    document = SimpleNamespace(status="active")
    session = AsyncMock()
    repository = DocumentRepository(session)
    repository.get_by_id = AsyncMock(return_value=document)

    assert await repository.soft_delete(uuid4(), uuid4()) is True
    assert document.status == "deleted"
    assert document.updated_at is not None
    assert document.updated_at.tzinfo is None
    session.delete.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_latest_version_query_is_scoped_and_orders_by_version_desc() -> None:
    document_id, organization_id = uuid4(), uuid4()
    result = SimpleNamespace(scalar_one_or_none=MagicMock(return_value=None))
    session = _session_with_result(result)

    assert await DocumentRepository(session).get_latest_version(
        document_id, organization_id
    ) is None

    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    sql = str(compiled)
    assert "documents.document_versions.document_id" in sql
    assert "documents.document_versions.organization_id" in sql
    assert "ORDER BY" in sql
    assert "version_number DESC" in sql
    assert document_id in compiled.params.values()
    assert organization_id in compiled.params.values()


def test_add_version_stages_metadata_and_never_commits() -> None:
    session = MagicMock()
    document_id, organization_id, uploaded_by = uuid4(), uuid4(), uuid4()

    version = DocumentRepository(session).add_version(
        document_id=document_id,
        organization_id=organization_id,
        version_number=2,
        original_filename="contract-v2.pdf",
        mime_type="application/pdf",
        file_size=4096,
        gcs_bucket="cicero-documents",
        gcs_object_name="org/case/document/v2.pdf",
        uploaded_by=uploaded_by,
        sha256_checksum="abc123",
    )

    assert isinstance(version, DocumentVersion)
    assert version.document_id == document_id
    assert version.organization_id == organization_id
    assert version.version_number == 2
    assert version.gcs_bucket == "cicero-documents"
    assert version.gcs_object_name == "org/case/document/v2.pdf"
    session.add.assert_called_once_with(version)
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    ("version_number", "file_size"),
    [(0, 100), (1, 0)],
)
def test_add_version_rejects_invalid_version_number_or_file_size(
    version_number: int, file_size: int
) -> None:
    repository = DocumentRepository(MagicMock())
    with pytest.raises(ValueError):
        repository.add_version(
            document_id=uuid4(),
            organization_id=uuid4(),
            version_number=version_number,
            original_filename="file.pdf",
            mime_type="application/pdf",
            file_size=file_size,
            gcs_bucket="bucket",
            gcs_object_name="object",
            uploaded_by=uuid4(),
        )


def test_repository_is_bound_to_document_model() -> None:
    assert DocumentRepository(AsyncMock()).model is Document
