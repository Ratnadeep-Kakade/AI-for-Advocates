from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.persistence.models.documents import (
    DocumentChunk,
    DocumentExtraction,
    DocumentProcessingRun,
)
from cicero.persistence.repositories.base import BaseRepository

PROCESSING_STATUSES = frozenset({"pending", "processing", "completed", "failed"})


class ProcessingRepository(BaseRepository[DocumentProcessingRun, UUID]):
    """Organization-scoped persistence for processing runs, extractions and chunks.

    This class persists ingestion outputs; it does not parse files, extract text,
    split content, generate embeddings, or access Google Cloud Storage. It never
    commits transactions. Authorization decisions remain in the service layer.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, DocumentProcessingRun, "processing_run_id")

    async def get_run(
        self, processing_run_id: UUID, organization_id: UUID
    ) -> DocumentProcessingRun | None:
        """Fetch a run only within the supplied organization."""
        statement = select(DocumentProcessingRun).where(
            DocumentProcessingRun.processing_run_id == processing_run_id,
            DocumentProcessingRun.organization_id == organization_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_run_for_document(
        self,
        processing_run_id: UUID,
        document_id: UUID,
        organization_id: UUID,
    ) -> DocumentProcessingRun | None:
        """Fetch a run using run, document and organization identifiers."""
        statement = select(DocumentProcessingRun).where(
            DocumentProcessingRun.processing_run_id == processing_run_id,
            DocumentProcessingRun.document_id == document_id,
            DocumentProcessingRun.organization_id == organization_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list_runs_for_document(
        self,
        document_id: UUID,
        organization_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentProcessingRun]:
        """List processing history for one organization-scoped document."""
        self._validate_pagination(limit, offset)
        if status is not None:
            self._validate_status(status)
        statement = select(DocumentProcessingRun).where(
            DocumentProcessingRun.document_id == document_id,
            DocumentProcessingRun.organization_id == organization_id,
        )
        if status is not None:
            statement = statement.where(
                DocumentProcessingRun.processing_status == status
            )
        statement = (
            statement.order_by(
                DocumentProcessingRun.created_at.desc(),
                DocumentProcessingRun.processing_run_id,
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_by_status(
        self,
        organization_id: UUID,
        status: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> list[DocumentProcessingRun]:
        """List runs in an organization with a given status."""
        self._validate_status(status)
        self._validate_pagination(limit, offset)
        statement = (
            select(DocumentProcessingRun)
            .where(
                DocumentProcessingRun.organization_id == organization_id,
                DocumentProcessingRun.processing_status == status,
            )
            .order_by(
                DocumentProcessingRun.created_at,
                DocumentProcessingRun.processing_run_id,
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    def create_run(
        self,
        *,
        version_id: UUID,
        document_id: UUID,
        organization_id: UUID,
        extraction_method: str | None = None,
        processing_metadata: dict[str, Any] | None = None,
    ) -> DocumentProcessingRun:
        """Stage a pending processing run for a document version."""
        run = DocumentProcessingRun(
            version_id=version_id,
            document_id=document_id,
            organization_id=organization_id,
            extraction_method=extraction_method,
            processing_metadata=dict(processing_metadata or {}),
        )
        self.session.add(run)
        return run

    async def set_status(
        self,
        processing_run_id: UUID,
        organization_id: UUID,
        status: str,
        *,
        error_message: str | None = None,
    ) -> DocumentProcessingRun | None:
        """Update run status and lifecycle timestamps.

        The database's CHECK constraint remains the final status validator. This
        method validates early and applies timestamps consistently: ``started_at``
        is set on transition to processing; ``completed_at`` is set for completed
        or failed runs. A non-failed status clears a stale error message.
        """
        self._validate_status(status)
        run = await self.get_run(processing_run_id, organization_id)
        if run is None:
            return None

        now = datetime.now(UTC).replace(tzinfo=None)
        run.processing_status = status
        if status == "processing" and run.started_at is None:
            run.started_at = now
        if status in {"completed", "failed"}:
            run.completed_at = now
        elif status in {"pending", "processing"}:
            run.completed_at = None
        run.error_message = error_message if status == "failed" else None
        return run

    async def update_metadata(
        self,
        processing_run_id: UUID,
        organization_id: UUID,
        metadata: dict[str, Any],
    ) -> DocumentProcessingRun | None:
        """Replace processing metadata for an organization-scoped run."""
        run = await self.get_run(processing_run_id, organization_id)
        if run is None:
            return None
        run.processing_metadata = dict(metadata)
        return run

    async def list_extractions_for_document(
        self,
        document_id: UUID,
        organization_id: UUID,
        *,
        version_id: UUID | None = None,
    ) -> list[DocumentExtraction]:
        """List extraction records, optionally restricted to one version."""
        statement = select(DocumentExtraction).where(
            DocumentExtraction.document_id == document_id,
            DocumentExtraction.organization_id == organization_id,
        )
        if version_id is not None:
            statement = statement.where(DocumentExtraction.version_id == version_id)
        statement = statement.order_by(
            DocumentExtraction.created_at.desc(), DocumentExtraction.extraction_id
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_extraction(
        self, extraction_id: UUID, organization_id: UUID
    ) -> DocumentExtraction | None:
        """Fetch an extraction within its organization."""
        statement = select(DocumentExtraction).where(
            DocumentExtraction.extraction_id == extraction_id,
            DocumentExtraction.organization_id == organization_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def create_extraction(
        self,
        *,
        processing_run_id: UUID,
        version_id: UUID,
        document_id: UUID,
        organization_id: UUID,
        extracted_text: str,
        page_count: int | None = None,
        extraction_metadata: dict[str, Any] | None = None,
    ) -> DocumentExtraction:
        """Stage extracted text and metadata for a completed ingestion step."""
        if page_count is not None and page_count < 0:
            raise ValueError("page_count must be non-negative")
        extraction = DocumentExtraction(
            processing_run_id=processing_run_id,
            version_id=version_id,
            document_id=document_id,
            organization_id=organization_id,
            extracted_text=extracted_text,
            page_count=page_count,
            extraction_metadata=dict(extraction_metadata or {}),
        )
        self.session.add(extraction)
        return extraction

    async def list_chunks_for_extraction(
        self, extraction_id: UUID, organization_id: UUID
    ) -> list[DocumentChunk]:
        """List chunks for an extraction in stable source order."""
        statement = (
            select(DocumentChunk)
            .where(
                DocumentChunk.extraction_id == extraction_id,
                DocumentChunk.organization_id == organization_id,
            )
            .order_by(DocumentChunk.chunk_index, DocumentChunk.chunk_id)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_chunks_for_document(
        self,
        document_id: UUID,
        organization_id: UUID,
        *,
        version_id: UUID | None = None,
        extraction_id: UUID | None = None,
    ) -> list[DocumentChunk]:
        """List chunks for a document, optionally scoped to version/extraction."""
        statement = select(DocumentChunk).where(
            DocumentChunk.document_id == document_id,
            DocumentChunk.organization_id == organization_id,
        )
        if version_id is not None:
            statement = statement.where(DocumentChunk.version_id == version_id)
        if extraction_id is not None:
            statement = statement.where(DocumentChunk.extraction_id == extraction_id)
        statement = statement.order_by(
            DocumentChunk.extraction_id,
            DocumentChunk.chunk_index,
            DocumentChunk.chunk_id,
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    def create_chunk(
        self,
        *,
        extraction_id: UUID,
        version_id: UUID,
        document_id: UUID,
        organization_id: UUID,
        chunk_index: int,
        content: str,
        page_start: int | None = None,
        page_end: int | None = None,
        start_char: int | None = None,
        end_char: int | None = None,
        token_count: int | None = None,
        chunking_version: str,
    ) -> DocumentChunk:
        """Stage one chunk while preserving its source-location metadata."""
        self._validate_chunk_fields(
            chunk_index=chunk_index,
            page_start=page_start,
            page_end=page_end,
            start_char=start_char,
            end_char=end_char,
            token_count=token_count,
            chunking_version=chunking_version,
        )
        chunk = DocumentChunk(
            extraction_id=extraction_id,
            version_id=version_id,
            document_id=document_id,
            organization_id=organization_id,
            chunk_index=chunk_index,
            content=content,
            page_start=page_start,
            page_end=page_end,
            start_char=start_char,
            end_char=end_char,
            token_count=token_count,
            chunking_version=chunking_version,
        )
        self.session.add(chunk)
        return chunk

    def create_chunks(
        self, chunks: Iterable[dict[str, Any]]
    ) -> list[DocumentChunk]:
        """Stage a batch of chunk records; caller owns flush/commit/rollback.

        Each mapping uses the same keyword fields as ``create_chunk``. This is a
        convenience for ingestion services and does not execute bulk SQL.
        """
        created = [self.create_chunk(**chunk) for chunk in chunks]
        return created

    @staticmethod
    def _validate_status(status: str) -> None:
        if status not in PROCESSING_STATUSES:
            raise ValueError(
                f"status must be one of: {', '.join(sorted(PROCESSING_STATUSES))}"
            )

    @staticmethod
    def _validate_pagination(limit: int, offset: int) -> None:
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")

    @staticmethod
    def _validate_chunk_fields(
        *,
        chunk_index: int,
        page_start: int | None,
        page_end: int | None,
        start_char: int | None,
        end_char: int | None,
        token_count: int | None,
        chunking_version: str,
    ) -> None:
        if chunk_index < 0:
            raise ValueError("chunk_index must be non-negative")
        if page_start is not None and page_end is not None and page_end < page_start:
            raise ValueError("page_end must be greater than or equal to page_start")
        if start_char is not None and start_char < 0:
            raise ValueError("start_char must be non-negative")
        if end_char is not None and end_char < 0:
            raise ValueError("end_char must be non-negative")
        if start_char is not None and end_char is not None and end_char < start_char:
            raise ValueError("end_char must be greater than or equal to start_char")
        if token_count is not None and token_count < 0:
            raise ValueError("token_count must be non-negative")
        if not chunking_version.strip():
            raise ValueError("chunking_version must not be empty")
