from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from cicero.db.models.documents import (
    DocumentChunk,
    DocumentExtraction,
    DocumentProcessingRun,
)
from cicero.db.repositories import ProcessingRepository


def _result_one(value: object = None) -> SimpleNamespace:
    return SimpleNamespace(scalar_one_or_none=MagicMock(return_value=value))


def _result_many(values: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        scalars=MagicMock(
            return_value=SimpleNamespace(all=MagicMock(return_value=values or []))
        )
    )


def _compiled(session: AsyncMock) -> tuple[str, dict[str, object]]:
    statement = session.execute.await_args.args[0]
    compiled = statement.compile(dialect=postgresql.dialect())
    return str(compiled), compiled.params


@pytest.mark.asyncio
async def test_get_run_is_organization_scoped() -> None:
    run_id, organization_id = uuid4(), uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_one())

    assert await ProcessingRepository(session).get_run(run_id, organization_id) is None

    sql, params = _compiled(session)
    assert "documents.document_processing_runs.processing_run_id" in sql
    assert "documents.document_processing_runs.organization_id" in sql
    assert run_id in params.values()
    assert organization_id in params.values()


@pytest.mark.asyncio
async def test_list_runs_for_document_scopes_and_filters_status() -> None:
    document_id, organization_id = uuid4(), uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_many())

    result = await ProcessingRepository(session).list_runs_for_document(
        document_id, organization_id, status="failed", limit=25, offset=5
    )

    assert result == []
    sql, params = _compiled(session)
    assert "documents.document_processing_runs.document_id" in sql
    assert "documents.document_processing_runs.organization_id" in sql
    assert "documents.document_processing_runs.processing_status" in sql
    assert document_id in params.values()
    assert organization_id in params.values()
    assert "failed" in params.values()
    assert "LIMIT" in sql and "OFFSET" in sql


@pytest.mark.asyncio
async def test_list_by_status_is_organization_scoped() -> None:
    organization_id = uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_many())

    await ProcessingRepository(session).list_by_status(
        organization_id, "pending"
    )

    sql, params = _compiled(session)
    assert "organization_id" in sql
    assert "processing_status" in sql
    assert organization_id in params.values()
    assert "pending" in params.values()


@pytest.mark.asyncio
async def test_invalid_status_and_pagination_are_rejected() -> None:
    repository = ProcessingRepository(AsyncMock())
    with pytest.raises(ValueError, match="status"):
        await repository.list_by_status(uuid4(), "queued")
    with pytest.raises(ValueError, match="limit"):
        await repository.list_runs_for_document(uuid4(), uuid4(), limit=0)
    with pytest.raises(ValueError, match="offset"):
        await repository.list_by_status(uuid4(), "pending", offset=-1)


def test_create_run_stages_pending_run_without_commit() -> None:
    session = MagicMock()
    version_id, document_id, organization_id = uuid4(), uuid4(), uuid4()

    run = ProcessingRepository(session).create_run(
        version_id=version_id,
        document_id=document_id,
        organization_id=organization_id,
        extraction_method="docling",
        processing_metadata={"source": "upload"},
    )

    assert isinstance(run, DocumentProcessingRun)
    assert run.version_id == version_id
    assert run.document_id == document_id
    assert run.organization_id == organization_id
    assert run.extraction_method == "docling"
    assert run.processing_metadata == {"source": "upload"}
    session.add.assert_called_once_with(run)
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_set_status_updates_lifecycle_fields() -> None:
    organization_id, run_id = uuid4(), uuid4()
    run = SimpleNamespace(
        processing_status="pending",
        started_at=None,
        completed_at=None,
        error_message=None,
    )
    repository = ProcessingRepository(AsyncMock())
    repository.get_run = AsyncMock(return_value=run)

    updated = await repository.set_status(
        run_id, organization_id, "failed", error_message="parser failed"
    )

    assert updated is run
    assert run.processing_status == "failed"
    assert run.started_at is None
    assert run.completed_at is not None
    assert run.completed_at.tzinfo is None
    assert run.error_message == "parser failed"
    repository.get_run.assert_awaited_once_with(run_id, organization_id)


@pytest.mark.asyncio
async def test_set_status_rejects_unknown_status_before_query() -> None:
    repository = ProcessingRepository(AsyncMock())
    with pytest.raises(ValueError, match="status"):
        await repository.set_status(uuid4(), uuid4(), "queued")


def test_create_extraction_stages_text_and_metadata() -> None:
    session = MagicMock()
    processing_run_id, version_id, document_id, organization_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )

    extraction = ProcessingRepository(session).create_extraction(
        processing_run_id=processing_run_id,
        version_id=version_id,
        document_id=document_id,
        organization_id=organization_id,
        extracted_text="Contract text",
        page_count=12,
        extraction_metadata={"parser": "docling"},
    )

    assert isinstance(extraction, DocumentExtraction)
    assert extraction.processing_run_id == processing_run_id
    assert extraction.version_id == version_id
    assert extraction.document_id == document_id
    assert extraction.organization_id == organization_id
    assert extraction.extracted_text == "Contract text"
    assert extraction.page_count == 12
    assert extraction.extraction_metadata == {"parser": "docling"}
    session.add.assert_called_once_with(extraction)
    session.commit.assert_not_called()


def test_create_extraction_rejects_negative_page_count() -> None:
    with pytest.raises(ValueError, match="page_count"):
        ProcessingRepository(MagicMock()).create_extraction(
            processing_run_id=uuid4(),
            version_id=uuid4(),
            document_id=uuid4(),
            organization_id=uuid4(),
            extracted_text="text",
            page_count=-1,
        )


@pytest.mark.asyncio
async def test_list_chunks_for_extraction_is_scoped_and_ordered() -> None:
    extraction_id, organization_id = uuid4(), uuid4()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=_result_many())

    assert await ProcessingRepository(session).list_chunks_for_extraction(
        extraction_id, organization_id
    ) == []

    sql, params = _compiled(session)
    assert "documents.document_chunks.extraction_id" in sql
    assert "documents.document_chunks.organization_id" in sql
    assert "ORDER BY" in sql
    assert "chunk_index" in sql
    assert extraction_id in params.values()
    assert organization_id in params.values()


def test_create_chunk_stages_source_metadata() -> None:
    session = MagicMock()
    extraction_id, version_id, document_id, organization_id = (
        uuid4(), uuid4(), uuid4(), uuid4()
    )

    chunk = ProcessingRepository(session).create_chunk(
        extraction_id=extraction_id,
        version_id=version_id,
        document_id=document_id,
        organization_id=organization_id,
        chunk_index=0,
        content="Section 1. Definitions",
        page_start=1,
        page_end=2,
        start_char=0,
        end_char=125,
        token_count=32,
        chunking_version="argon-v3.2",
    )

    assert isinstance(chunk, DocumentChunk)
    assert chunk.extraction_id == extraction_id
    assert chunk.version_id == version_id
    assert chunk.document_id == document_id
    assert chunk.organization_id == organization_id
    assert chunk.chunk_index == 0
    assert chunk.content == "Section 1. Definitions"
    assert chunk.page_start == 1 and chunk.page_end == 2
    assert chunk.start_char == 0 and chunk.end_char == 125
    assert chunk.token_count == 32
    assert chunk.chunking_version == "argon-v3.2"
    session.add.assert_called_once_with(chunk)
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "overrides",
    [
        {"chunk_index": -1},
        {"page_start": 3, "page_end": 2},
        {"start_char": -1},
        {"start_char": 5, "end_char": 4},
        {"token_count": -1},
        {"chunking_version": "   "},
    ],
)
def test_create_chunk_rejects_invalid_source_metadata(
    overrides: dict[str, object],
) -> None:
    values: dict[str, object] = {
        "extraction_id": uuid4(),
        "version_id": uuid4(),
        "document_id": uuid4(),
        "organization_id": uuid4(),
        "chunk_index": 0,
        "content": "text",
        "page_start": 1,
        "page_end": 1,
        "start_char": 0,
        "end_char": 4,
        "token_count": 1,
        "chunking_version": "v1",
    }
    values.update(overrides)
    with pytest.raises(ValueError):
        ProcessingRepository(MagicMock()).create_chunk(**values)  # type: ignore[arg-type]


def test_create_chunks_stages_all_chunks() -> None:
    session = MagicMock()
    common = {
        "extraction_id": uuid4(),
        "version_id": uuid4(),
        "document_id": uuid4(),
        "organization_id": uuid4(),
        "content": "text",
        "chunking_version": "v1",
    }

    chunks = ProcessingRepository(session).create_chunks(
        [
            {**common, "chunk_index": 0},
            {**common, "chunk_index": 1},
        ]
    )

    assert len(chunks) == 2
    assert all(isinstance(chunk, DocumentChunk) for chunk in chunks)
    assert session.add.call_count == 2
    session.commit.assert_not_called()


def test_repository_is_bound_to_processing_run_model() -> None:
    assert ProcessingRepository(AsyncMock()).model is DocumentProcessingRun
