from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKeyConstraint,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from cicero.persistence.base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        ForeignKeyConstraint(
            ["case_id", "organization_id"],
            ["cases.cases.case_id", "cases.cases.organization_id"],
            name="documents_case_id_organization_id_fkey",
        ),
        ForeignKeyConstraint(
            ["uploaded_by"], ["auth.users.user_id"], name="documents_uploaded_by_fkey"
        ),
        UniqueConstraint(
            "document_id",
            "organization_id",
            name="documents_document_id_organization_id_key",
        ),
        CheckConstraint(
            "status = ANY (ARRAY['active'::text, 'archived'::text, 'deleted'::text])",
            name="documents_status_check",
        ),
        Index("idx_documents_case", "case_id"),
        Index("idx_documents_organization", "organization_id"),
        {"schema": "documents"},
    )

    document_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    case_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    uploaded_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    document_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'active'"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["document_id", "organization_id"],
            ["documents.documents.document_id", "documents.documents.organization_id"],
            name="document_versions_document_id_organization_id_fkey",
        ),
        ForeignKeyConstraint(
            ["uploaded_by"],
            ["auth.users.user_id"],
            name="document_versions_uploaded_by_fkey",
        ),
        UniqueConstraint(
            "document_id",
            "version_number",
            name="document_versions_document_id_version_number_key",
        ),
        UniqueConstraint(
            "gcs_bucket",
            "gcs_object_name",
            name="document_versions_gcs_bucket_gcs_object_name_key",
        ),
        UniqueConstraint(
            "version_id",
            "document_id",
            "organization_id",
            name="document_versions_version_id_document_id_organization_id_key",
        ),
        CheckConstraint("file_size > 0", name="document_versions_file_size_check"),
        CheckConstraint("version_number > 0", name="document_versions_version_number_check"),
        Index("idx_document_versions_document", "document_id"),
        {"schema": "documents"},
    )

    version_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(Text, nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    gcs_bucket: Mapped[str] = mapped_column(Text, nullable=False)
    gcs_object_name: Mapped[str] = mapped_column(Text, nullable=False)
    sha256_checksum: Mapped[str | None] = mapped_column(Text)
    uploaded_by: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DocumentProcessingRun(Base):
    __tablename__ = "document_processing_runs"
    __table_args__ = (
        ForeignKeyConstraint(
            ["version_id", "document_id", "organization_id"],
            [
                "documents.document_versions.version_id",
                "documents.document_versions.document_id",
                "documents.document_versions.organization_id",
            ],
            name="document_processing_runs_version_id_document_id_organizati_fkey",
        ),
        UniqueConstraint(
            "processing_run_id",
            "version_id",
            "document_id",
            "organization_id",
            name="document_processing_runs_processing_run_id_version_id_docum_key",
        ),
        CheckConstraint(
            "processing_status = ANY (ARRAY['pending'::text, 'processing'::text, "
            "'completed'::text, 'failed'::text])",
            name="document_processing_runs_processing_status_check",
        ),
        Index("idx_processing_status", "processing_status"),
        Index("idx_processing_version", "version_id"),
        {"schema": "documents"},
    )

    processing_run_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    processing_status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'pending'")
    )
    extraction_method: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(Text)
    processing_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["processing_run_id", "version_id", "document_id", "organization_id"],
            [
                "documents.document_processing_runs.processing_run_id",
                "documents.document_processing_runs.version_id",
                "documents.document_processing_runs.document_id",
                "documents.document_processing_runs.organization_id",
            ],
            name="document_extractions_processing_run_id_version_id_document_fkey",
        ),
        UniqueConstraint(
            "extraction_id",
            "version_id",
            "document_id",
            "organization_id",
            name="document_extractions_extraction_id_version_id_document_id_o_key",
        ),
        Index("idx_extractions_document", "document_id"),
        {"schema": "documents"},
    )

    extraction_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    processing_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extraction_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_id", "version_id", "document_id", "organization_id"],
            [
                "documents.document_extractions.extraction_id",
                "documents.document_extractions.version_id",
                "documents.document_extractions.document_id",
                "documents.document_extractions.organization_id",
            ],
            name="document_chunks_extraction_id_version_id_document_id_organ_fkey",
        ),
        UniqueConstraint(
            "extraction_id",
            "chunk_index",
            name="document_chunks_extraction_id_chunk_index_key",
        ),
        CheckConstraint("chunk_index >= 0", name="document_chunks_chunk_index_check"),
        Index("idx_chunks_case", "organization_id", "document_id"),
        Index("idx_chunks_document", "document_id"),
        {"schema": "documents"},
    )

    chunk_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, server_default=text("gen_random_uuid()")
    )
    extraction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    version_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    document_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    organization_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    start_char: Mapped[int | None] = mapped_column(Integer)
    end_char: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int | None] = mapped_column(Integer)
    chunking_version: Mapped[str] = mapped_column(Text, nullable=False)
    # Added by migration 20261104_0002 (legal RAG); written by the worker.
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1024))
    embedding_text: Mapped[str | None] = mapped_column(Text)
    parent_chunk_key: Mapped[str | None] = mapped_column(Text)
    chunk_type: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'clause'"))
    section_path: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    legal_identifiers: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("ARRAY[]::text[]")
    )
    chunk_metadata: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    search_vector: Mapped[str | None] = mapped_column(TSVECTOR)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
