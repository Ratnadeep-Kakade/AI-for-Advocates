from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cicero.persistence.models.documents import Document, DocumentVersion
from cicero.persistence.repositories.base import BaseRepository


class _UnsetType:
    """Sentinel type distinguishing an omitted optional update from explicit None."""


_UNSET = _UnsetType()


class DocumentRepository(BaseRepository[Document, UUID]):
    """Organization-scoped database operations for documents and versions.

    This repository never deletes objects from Google Cloud Storage. It only
    manages PostgreSQL records. Authorization decisions remain in the service
    layer, and transaction ownership remains with the caller.
    """

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Document, "document_id")

    async def get_by_id(
        self, document_id: UUID, *, organization_id: UUID
    ) -> Document | None:
        """Fetch a document only when its organization matches."""
        statement = select(Document).where(
            Document.document_id == document_id,
            Document.organization_id == organization_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_by_id_and_organization(
        self, document_id: UUID, organization_id: UUID
    ) -> Document | None:
        """Explicitly named equivalent of the scoped ``get_by_id``."""
        return await self.get_by_id(document_id, organization_id=organization_id)

    async def list_by_case(
        self,
        case_id: UUID,
        organization_id: UUID,
        *,
        status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Document]:
        """List documents for a case, always constrained by organization."""
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be non-negative")

        statement = select(Document).where(
            Document.case_id == case_id,
            Document.organization_id == organization_id,
        )
        if status is not None:
            statement = statement.where(Document.status == status)
        statement = (
            statement.order_by(Document.updated_at.desc(), Document.document_id)
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    def create_document(
        self,
        *,
        case_id: UUID,
        organization_id: UUID,
        uploaded_by: UUID,
        title: str,
        document_type: str | None = None,
    ) -> Document:
        """Stage a document record. The caller must authorize case access first."""
        normalized_title = title.strip()
        if not normalized_title:
            raise ValueError("title must not be empty")
        document = Document(
            case_id=case_id,
            organization_id=organization_id,
            uploaded_by=uploaded_by,
            title=normalized_title,
            document_type=document_type,
        )
        self.session.add(document)
        return document

    async def update_details(
        self,
        document_id: UUID,
        organization_id: UUID,
        *,
        title: str | None = None,
        document_type: str | None | _UnsetType = _UNSET,
    ) -> Document | None:
        """Update document descriptive fields without changing its ownership.

        Passing ``document_type=None`` clears it. Omitting the argument leaves
        it unchanged. An empty title is rejected rather than stored.
        """
        document = await self.get_by_id(
            document_id, organization_id=organization_id
        )
        if document is None:
            return None
        if title is not None:
            normalized_title = title.strip()
            if not normalized_title:
                raise ValueError("title must not be empty")
            document.title = normalized_title
        if document_type is not _UNSET:
            document.document_type = document_type
        document.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return document

    async def set_status(
        self, document_id: UUID, organization_id: UUID, status: str
    ) -> Document | None:
        """Set a database document status; PostgreSQL validates allowed values."""
        document = await self.get_by_id(
            document_id, organization_id=organization_id
        )
        if document is None:
            return None
        document.status = status
        document.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return document

    async def soft_delete(
        self, document_id: UUID, organization_id: UUID
    ) -> bool:
        """Mark a document deleted without deleting its row or GCS objects."""
        document = await self.get_by_id(
            document_id, organization_id=organization_id
        )
        if document is None:
            return False
        document.status = "deleted"
        document.updated_at = datetime.now(UTC).replace(tzinfo=None)
        return True

    async def list_versions(
        self, document_id: UUID, organization_id: UUID
    ) -> list[DocumentVersion]:
        """Return version history for a document within the organization."""
        statement = (
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.organization_id == organization_id,
            )
            .order_by(
                DocumentVersion.version_number.desc(),
                DocumentVersion.created_at.desc(),
            )
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def get_version(
        self,
        version_id: UUID,
        document_id: UUID,
        organization_id: UUID,
    ) -> DocumentVersion | None:
        """Fetch a version using all three ownership identifiers."""
        statement = select(DocumentVersion).where(
            DocumentVersion.version_id == version_id,
            DocumentVersion.document_id == document_id,
            DocumentVersion.organization_id == organization_id,
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def get_latest_version(
        self, document_id: UUID, organization_id: UUID
    ) -> DocumentVersion | None:
        """Return the highest-numbered version for an organization-scoped document."""
        statement = (
            select(DocumentVersion)
            .where(
                DocumentVersion.document_id == document_id,
                DocumentVersion.organization_id == organization_id,
            )
            .order_by(
                DocumentVersion.version_number.desc(),
                DocumentVersion.created_at.desc(),
            )
            .limit(1)
        )
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    def add_version(
        self,
        *,
        document_id: UUID,
        organization_id: UUID,
        version_number: int,
        original_filename: str,
        mime_type: str,
        file_size: int,
        gcs_bucket: str,
        gcs_object_name: str,
        uploaded_by: UUID,
        sha256_checksum: str | None = None,
    ) -> DocumentVersion:
        """Stage version metadata; does not upload or delete the GCS object.

        ``version_number`` is supplied by the service. The database unique
        constraint remains the final guard against concurrent duplicate numbers.
        """
        if version_number < 1:
            raise ValueError("version_number must be positive")
        if file_size < 1:
            raise ValueError("file_size must be positive")
        version = DocumentVersion(
            document_id=document_id,
            organization_id=organization_id,
            version_number=version_number,
            original_filename=original_filename,
            mime_type=mime_type,
            file_size=file_size,
            gcs_bucket=gcs_bucket,
            gcs_object_name=gcs_object_name,
            uploaded_by=uploaded_by,
            sha256_checksum=sha256_checksum,
        )
        self.session.add(version)
        return version
