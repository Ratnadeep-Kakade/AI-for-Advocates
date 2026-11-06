from __future__ import annotations

import asyncio
import base64
import gc
import hmac
import json
import logging
import os
import re
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import FastAPI, Header, HTTPException, Request
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.cloud import storage
from google.oauth2 import id_token
from sqlalchemy import select, text

from cicero.auth.google_credentials import GoogleCredentialsProvider
from cicero.config import Settings, get_settings
from cicero.db.connection import DatabaseManager
from cicero.db.models.documents import Document, DocumentProcessingRun, DocumentVersion
from cicero.db.repositories.processing import ProcessingRepository
from cicero.rag.argon.embeddings_and_qdrant import BGEM3Embedder, CrossEncoderReranker
from cicero.rag.argon.schemas import (
    EvidenceItem,
    EvidencePack,
    ModelRuntimeMetadata,
    QueryDiagnostics,
    RawTable,
    TableCellProvenance,
    ValidationStatus,
    extract_legal_identifiers,
)
from cicero.rag.argon.structural_processor import LegalTableProcessor
from cicero.rag.pipeline import LegalRagPipeline, json_safe
from cicero.rag.retrieval import (
    INDEXABLE_CHUNK_TYPES,
    EvidenceValidator,
    ParsedDocView,
    QueryRouter,
    estimate_tokens,
    pack_context,
    reciprocal_rank_fusion,
)

logger = logging.getLogger("cicero.rag_worker")

SUPPORTED_MIME_TYPES = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


def _safe_date_iso(val: Any) -> str | None:
    if not val or not isinstance(val, str):
        return None
    try:
        from datetime import date
        parts = [int(p) for p in val.strip().split("-")]
        if len(parts) == 3:
            return date(parts[0], parts[1], parts[2]).isoformat()
    except Exception:
        pass
    return None


class ProcessingAlreadyRunning(RuntimeError):
    """Raised for a duplicate Pub/Sub delivery while a live worker owns the run."""


class RagWorker:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.database = DatabaseManager(settings)
        # Modal workers authenticate through Workload Identity Federation;
        # local/Cloud Run runs fall back to Application Default Credentials.
        credentials = GoogleCredentialsProvider(settings).load()
        self.storage = storage.Client(
            project=settings.gcs_project_id, credentials=credentials
        )
        self.pipeline: LegalRagPipeline | None = None
        self.embedder: BGEM3Embedder | None = None
        self.reranker: CrossEncoderReranker | None = None
        self.router = QueryRouter()
        self.table_processor = LegalTableProcessor()

    async def start(self) -> None:
        await self.database.start()

    async def close(self) -> None:
        await self.database.close()

    def _device(self) -> str | None:
        """Resolve the compute device: None lets the stack auto-select CUDA."""
        device = (self.settings.rag_device or "auto").strip().lower()
        return None if device == "auto" else device

    def _load_embedder(self) -> None:
        if self.embedder is None:
            self.embedder = BGEM3Embedder(
                model_name="BAAI/bge-m3",
                device=self._device(),
                max_length=2048,
                expected_dim=1024,
                simulation_mode=False,
            )

    def _load_pipeline_only(self) -> None:
        if self.pipeline is None:
            # Parser mode from settings: "pdfplumber" (default) skips the
            # Docling converter entirely — its layout/OCR models OOM-killed
            # memory-capped worker containers even on small PDFs. The
            # pdfplumber extractor still yields page-anchored text blocks
            # for hierarchy/chunking/embedding. Set CICERO_RAG_PARSER_MODE=
            # docling on a large-memory worker for the full pipeline.
            use_docling = (self.settings.rag_parser_mode or "pdfplumber").lower() == "docling"
            self.pipeline = LegalRagPipeline(enable_ocr=False, use_docling=use_docling)

    def _load_ingestion_components(self) -> None:
        self._load_pipeline_only()
        self._load_embedder()

    def _load_retrieval_components(self) -> None:
        self._load_embedder()
        if self.reranker is None:
            self.reranker = CrossEncoderReranker(
                model_name="BAAI/bge-reranker-v2-m3",
                device=self._device(),
                rejection_threshold=self.settings.rag_rerank_threshold,
                simulation_mode=False,
            )

    async def _set_run_state(
        self, processing_run_id: UUID, organization_id: UUID, state: str
    ) -> None:
        factory = self.database.session_factory
        if factory is None:
            return
        try:
            async with factory() as session:
                async with session.begin():
                    run = await ProcessingRepository(session).get_run(
                        processing_run_id, organization_id
                    )
                    if run is not None:
                        run.processing_metadata = {
                            **(run.processing_metadata or {}),
                            "state": state,
                        }
        except Exception:
            logger.warning("Could not update processing state", exc_info=True)

    async def _heartbeat(
        self, processing_run_id: UUID, organization_id: UUID, stop: asyncio.Event
    ) -> None:
        """Extend the processing lease while a long document is being ingested."""
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=600)
            except TimeoutError:
                factory = self.database.session_factory
                if factory is None:
                    continue
                try:
                    async with factory() as session:
                        async with session.begin():
                            run = await ProcessingRepository(session).get_run(
                                processing_run_id, organization_id
                            )
                            if run is not None and run.processing_status == "processing":
                                run.processing_metadata = {
                                    **(run.processing_metadata or {}),
                                    "worker_lock_until": (
                                        datetime.now(UTC).replace(tzinfo=None)
                                        + timedelta(minutes=self.settings.rag_lease_minutes)
                                    ).isoformat(),
                                }
                except Exception:
                    logger.warning("Processing heartbeat failed", exc_info=True)

    async def process_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        organization_id = UUID(payload["organization_id"])
        document_id = UUID(payload["document_id"])
        version_id = UUID(payload["version_id"])
        processing_run_id = UUID(payload["processing_run_id"])
        factory = self.database.session_factory
        if factory is None:
            raise RuntimeError("Cloud SQL session factory is unavailable")

        async with factory() as session:
            record = await session.execute(
                select(DocumentVersion, DocumentProcessingRun, Document)
                .join(
                    Document,
                    (Document.document_id == DocumentVersion.document_id)
                    & (Document.organization_id == DocumentVersion.organization_id),
                )
                .join(
                    DocumentProcessingRun,
                    (DocumentProcessingRun.version_id == DocumentVersion.version_id)
                    & (DocumentProcessingRun.document_id == DocumentVersion.document_id)
                    & (DocumentProcessingRun.organization_id == DocumentVersion.organization_id),
                )
                .where(
                    DocumentVersion.version_id == version_id,
                    DocumentVersion.document_id == document_id,
                    DocumentVersion.organization_id == organization_id,
                    Document.case_id == UUID(payload["case_id"]),
                    Document.status == "active",
                    DocumentProcessingRun.processing_run_id == processing_run_id,
                )
                .with_for_update(of=DocumentProcessingRun)
            )
            row = record.one_or_none()
            if row is None:
                raise ValueError(
                    "Processing run or document version was not found in this organization"
                )
            version, run, _document = row
            if run.processing_status == "completed":
                return {"status": "already_completed", "processing_run_id": str(processing_run_id)}
            metadata = dict(run.processing_metadata or {})
            lock_until = metadata.get("worker_lock_until")
            # force_reclaim is set only by the operator re-drive path (a
            # trusted Modal spawn, never by Pub/Sub payloads): the previous
            # worker is known dead, so its unexpired lease must not block.
            if run.processing_status == "processing" and lock_until and not payload.get(
                "force_reclaim"
            ):
                if datetime.fromisoformat(str(lock_until)) > datetime.now(UTC).replace(tzinfo=None):
                    raise ProcessingAlreadyRunning(
                        "This processing run is already being handled by another worker"
                    )
            now = datetime.now(UTC).replace(tzinfo=None)
            run.processing_status = "processing"
            run.started_at = run.started_at or now
            run.error_message = None
            run.processing_metadata = {
                **metadata,
                "worker": "cloud-run",
                "state": "downloading",
                "worker_lock_until": (
                    now + timedelta(minutes=self.settings.rag_lease_minutes)
                ).isoformat(),
            }
            await session.commit()
            bucket_name, object_name = version.gcs_bucket, version.gcs_object_name
            if bucket_name != self.settings.gcs_bucket_name:
                raise ValueError("Document version references an unexpected GCS bucket")

        stop_heartbeat = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat(processing_run_id, organization_id, stop_heartbeat)
        )
        try:
            suffix = Path(version.original_filename).suffix or ".pdf"
            with tempfile.TemporaryDirectory(prefix="cicero-ingest-") as tmp:
                safe_filename = Path(version.original_filename).name
                local_name = safe_filename or f"{document_id}{suffix}"
                local_path = str(Path(tmp) / local_name)
                expected_prefix = (
                    f"orgs/{organization_id}/cases/{payload['case_id']}/documents/"
                    f"{document_id}/versions/{version_id}/"
                )
                if not object_name.startswith(expected_prefix):
                    raise ValueError(
                        "Stored GCS object path does not match the document tenant/version"
                    )
                blob = self.storage.bucket(bucket_name).blob(object_name)
                await asyncio.to_thread(blob.reload)
                document_type = SUPPORTED_MIME_TYPES.get(blob.content_type or "")
                if document_type is None:
                    raise ValueError("Stored object is not a supported PDF or DOCX document")
                if not blob.size or blob.size > self.settings.gcs_max_file_size_bytes:
                    raise ValueError(
                        "Stored document is empty or exceeds the configured size limit"
                    )
                await asyncio.to_thread(blob.download_to_filename, local_path)
                with open(local_path, "rb") as doc_file:
                    file_head = doc_file.read(5)
                if document_type == "pdf" and not file_head.startswith(b"%PDF-"):
                    raise ValueError("Uploaded file does not have a valid PDF signature")
                if document_type == "docx" and not file_head.startswith(b"PK\x03\x04"):
                    raise ValueError("Uploaded file does not have a valid DOCX (zip) signature")
                await self._set_run_state(processing_run_id, organization_id, "parsing")
                # Load only the parser for the parse phase. Loading BGE-M3
                # first leaves the embedder resident (~2 GB+) alongside
                # Docling's layout/OCR models and OOM-killed the Modal
                # container (default memory request) on a small patent PDF.
                await asyncio.to_thread(self._load_pipeline_only)
                assert self.pipeline is not None
                result = await asyncio.to_thread(
                    self.pipeline.process_document,
                    local_path,
                    document_id=str(document_id),
                    case_id=str(payload["case_id"]),
                    organization_id=str(organization_id),
                    document_type=document_type,
                )
                self.pipeline = None
                await asyncio.to_thread(gc.collect)
                await asyncio.to_thread(self._load_embedder)
                assert self.embedder is not None
                await self._set_run_state(processing_run_id, organization_id, "embedding")
                chunk_objects = result["chunks"]
                indexable = [
                    (idx, chunk)
                    for idx, chunk in enumerate(chunk_objects)
                    if chunk.chunk_type in INDEXABLE_CHUNK_TYPES
                ]
                vectors: dict[int, Any] = {}
                if indexable:
                    encoded = await asyncio.to_thread(
                        self.embedder.encode_batch,
                        [chunk.embedding_text for _, chunk in indexable],
                        batch_size=8,
                    )
                    vectors = {
                        idx: row
                        for (idx, _), row in zip(indexable, encoded["dense_vecs"], strict=True)
                    }
                def _release_memory() -> None:
                    gc.collect()
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception:
                        pass

                await asyncio.to_thread(_release_memory)
                await self._set_run_state(processing_run_id, organization_id, "storing")
                await self._persist_result(
                    organization_id=organization_id,
                    document_id=document_id,
                    version_id=version_id,
                    processing_run_id=processing_run_id,
                    result=result,
                    vectors=vectors,
                )
            return {
                "status": "completed",
                "processing_run_id": str(processing_run_id),
                "document_type": document_type,
                "chunks": len(result["chunks"]),
                "embedded_chunks": len(indexable),
                "pages": len(result["parsed"].pages),
                "definitions": len(result["definitions"]),
                "cross_references": len(result["cross_references"]),
                "tables": len(result["parsed"].tables),
            }
        finally:
            stop_heartbeat.set()
            heartbeat_task.cancel()

    async def _persist_result(
        self,
        *,
        organization_id: UUID,
        document_id: UUID,
        version_id: UUID,
        processing_run_id: UUID,
        result: dict[str, Any],
        vectors: dict[int, Any],
    ) -> None:
        factory = self.database.session_factory
        assert factory is not None
        parsed = result["parsed"]
        async with factory() as session:
            async with session.begin():
                repo = ProcessingRepository(session)
                run = await repo.get_run(processing_run_id, organization_id)
                if run is None:
                    raise ValueError("Processing run disappeared before persistence")
                # Idempotent re-ingestion: a redelivered/crashed run must not
                # duplicate the version index. Replace prior artefacts first.
                scope = {"org": organization_id, "version": version_id}
                await session.execute(
                    text(
                        "DELETE FROM documents.document_chunks "
                        "WHERE organization_id = :org AND version_id = :version"
                    ),
                    scope,
                )
                await session.execute(
                    text(
                        "DELETE FROM documents.document_extractions "
                        "WHERE organization_id = :org AND version_id = :version"
                    ),
                    scope,
                )
                for table_name in (
                    "legal_hierarchy_nodes",
                    "legal_definitions",
                    "legal_cross_references",
                    "legal_dates",
                    "legal_tables",
                ):
                    await session.execute(
                        text(
                            f"DELETE FROM intelligence.{table_name} "
                            "WHERE organization_id = :org AND version_id = :version"
                        ),
                        scope,
                    )
                extraction = repo.create_extraction(
                    processing_run_id=processing_run_id,
                    version_id=version_id,
                    document_id=document_id,
                    organization_id=organization_id,
                    extracted_text=parsed.full_text,
                    page_count=len(parsed.pages),
                    extraction_metadata={
                        "parser_version": parsed.parser_version,
                        "ingestion_status": parsed.ingestion_status,
                        "file_sha256": result["file_sha256"],
                        "structure_confidence": result["structure_confidence"],
                        "warnings": result["warnings"],
                        "pages": json_safe(parsed.pages),
                        "parser_metadata": json_safe(parsed.metadata),
                        "dates": json_safe(result["dates"]),
                        "tokenizer": result.get("tokenizer"),
                    },
                )
                await session.flush()
                # Batch the per-chunk writes: a 500-600 page document yields
                # thousands of chunks, so flush once and use executemany.
                staged: list[tuple[int, Any, Any]] = []
                for idx, chunk in enumerate(result["chunks"]):
                    db_chunk = repo.create_chunk(
                        extraction_id=extraction.extraction_id,
                        version_id=version_id,
                        document_id=document_id,
                        organization_id=organization_id,
                        chunk_index=idx,
                        content=chunk.clean_text,
                        page_start=chunk.page,
                        page_end=chunk.page,
                        start_char=chunk.char_start,
                        end_char=chunk.char_end,
                        token_count=chunk.token_count,
                        chunking_version="argon-hierarchical-v1",
                    )
                    staged.append((idx, chunk, db_chunk))
                await session.flush()
                vec_params: list[dict[str, Any]] = []
                meta_params: list[dict[str, Any]] = []
                for idx, chunk, db_chunk in staged:
                    base_params: dict[str, Any] = {
                        "embedding_text": chunk.embedding_text,
                        "chunk_type": chunk.chunk_type,
                        "section_path": chunk.section_path,
                        "identifiers": chunk.legal_identifiers,
                        "parent_key": chunk.parent_id,
                        "metadata": json.dumps(
                            {
                                "chunk_key": chunk.chunk_id,
                                "node_id": chunk.node_id,
                                "parent_id": chunk.parent_id,
                                "clause_label": chunk.clause_label,
                                "bbox": chunk.bbox,
                                "structure_confidence": chunk.structure_confidence,
                                "tokenizer": chunk.tokenizer_name,
                                "effective_date": chunk.effective_date,
                                "expiration_date": chunk.expiration_date,
                                "table_id": chunk.table_id,
                                "retrieval_aid_only": chunk.retrieval_aid_only,
                            }
                        ),
                        "chunk_id": db_chunk.chunk_id,
                    }
                    vec_row = vectors.get(idx)
                    if vec_row is not None:
                        vec_params.append(
                            {
                                **base_params,
                                "embedding": "["
                                + ",".join(f"{float(v):.8f}" for v in vec_row)
                                + "]",
                            }
                        )
                    else:
                        meta_params.append(base_params)
                if vec_params:
                    await session.execute(
                        text(
                            "UPDATE documents.document_chunks SET embedding = "
                            "CAST(:embedding AS vector), "
                            "embedding_text = :embedding_text, chunk_type = :chunk_type, "
                            "section_path = :section_path, legal_identifiers = :identifiers, "
                            "parent_chunk_key = :parent_key, "
                            "chunk_metadata = CAST(:metadata AS jsonb) "
                            "WHERE chunk_id = :chunk_id"
                        ),
                        vec_params,
                    )
                if meta_params:
                    await session.execute(
                        text(
                            "UPDATE documents.document_chunks SET "
                            "embedding_text = :embedding_text, chunk_type = :chunk_type, "
                            "section_path = :section_path, legal_identifiers = :identifiers, "
                            "parent_chunk_key = :parent_key, "
                            "chunk_metadata = CAST(:metadata AS jsonb) "
                            "WHERE chunk_id = :chunk_id"
                        ),
                        meta_params,
                    )
                try:
                    if result.get("nodes"):
                        statement = text(
                            "INSERT INTO intelligence.legal_hierarchy_nodes "
                            "(node_id, organization_id, case_id, document_id, version_id, "
                            "extraction_id, parent_node_id, level, label, page_start, "
                            "page_end, char_start, char_end, node_data) "
                            "VALUES (:node_id, :org, :case_id, :doc, :version, "
                            ":extraction, :parent, "
                            " :level, :label, :page_start, :page_end, :char_start, "
                            ":char_end, CAST(:data AS jsonb))"
                        )
                        node_params = [
                            {
                                "node_id": node.node_id,
                                "org": organization_id,
                                "case_id": UUID(parsed.case_id),
                                "doc": document_id,
                                "version": version_id,
                                "extraction": extraction.extraction_id,
                                "parent": node.parent_id,
                                "level": node.level,
                                "label": node.label,
                                "page_start": node.page_start,
                                "page_end": node.page_end,
                                "char_start": node.char_start,
                                "char_end": node.char_end,
                                "data": json.dumps(json_safe(node)),
                            }
                            for node in result["nodes"]
                        ]
                        await session.execute(statement, node_params)
                except Exception as exc:
                    logger.warning("Could not persist legal hierarchy nodes: %s", exc)

                try:
                    if result.get("definitions"):
                        statement = text(
                            "INSERT INTO intelligence.legal_definitions "
                            "(organization_id, case_id, document_id, version_id, "
                            "extraction_id, term, "
                            " verbatim_definition, normalized_meaning, page, "
                            "char_start, char_end, "
                            "     definition_data) "
                            "VALUES (:org, :case_id, :doc, :version, :extraction, :term, "
                            ":definition, "
                            " :meaning, :page, :start, :end, CAST(:data AS jsonb))"
                        )
                        def_params = [
                            {
                                "org": organization_id,
                                "case_id": UUID(parsed.case_id),
                                "doc": document_id,
                                "version": version_id,
                                "extraction": extraction.extraction_id,
                                "term": definition.term,
                                "definition": definition.definition,
                                "meaning": definition.extracted_meaning,
                                "page": definition.page,
                                "start": definition.char_start,
                                "end": definition.char_end,
                                "data": json.dumps(json_safe(definition)),
                            }
                            for definition in result["definitions"]
                        ]
                        await session.execute(statement, def_params)
                except Exception as exc:
                    logger.warning("Could not persist legal definitions: %s", exc)

                try:
                    if result.get("cross_references"):
                        statement = text(
                            "INSERT INTO intelligence.legal_cross_references "
                            "(edge_id, organization_id, case_id, document_id, version_id, "
                            "extraction_id, "
                            " from_node_id, to_node_id, target_label, normalized_reference, "
                            "     resolution_status, "
                            " source_provenance, edge_data) "
                            "VALUES (:edge_id, :org, :case_id, :doc, :version, :extraction, "
                            ":from_node, "
                            " :to_node, :target, :normalized, :status, "
                            "CAST(:provenance AS jsonb), "
                            "     CAST(:data AS jsonb))"
                        )
                        ref_params = [
                            {
                                "edge_id": edge.edge_id,
                                "org": organization_id,
                                "case_id": UUID(parsed.case_id),
                                "doc": document_id,
                                "version": version_id,
                                "extraction": extraction.extraction_id,
                                "from_node": edge.from_node,
                                "to_node": edge.to_node,
                                "target": edge.target_label,
                                "normalized": edge.normalized_reference,
                                "status": edge.resolution_status,
                                "provenance": json.dumps(json_safe(edge.source_provenance)),
                                "data": json.dumps(json_safe(edge)),
                            }
                            for edge in result["cross_references"]
                        ]
                        await session.execute(statement, ref_params)
                except Exception as exc:
                    logger.warning("Could not persist legal cross references: %s", exc)

                try:
                    if result.get("dates"):
                        statement = text(
                            "INSERT INTO intelligence.legal_dates "
                            "(date_id, organization_id, case_id, document_id, version_id, "
                            "extraction_id, "
                            " normalized_date, raw_date, date_role, page, "
                            "char_start, char_end, "
                            "     ambiguous, date_data) "
                            "VALUES (:date_id, :org, :case_id, :doc, :version, :extraction, "
                            " CAST(:normalized AS date), :raw, :role, :page, "
                            ":start, :end, :ambiguous, "
                            "     CAST(:data AS jsonb))"
                        )
                        date_params = [
                            {
                                "date_id": date_record.date_id,
                                "org": organization_id,
                                "case_id": UUID(parsed.case_id),
                                "doc": document_id,
                                "version": version_id,
                                "extraction": extraction.extraction_id,
                                "normalized": _safe_date_iso(date_record.iso),
                                "raw": date_record.raw,
                                "role": date_record.role,
                                "page": date_record.page,
                                "start": date_record.char_start,
                                "end": date_record.char_end,
                                "ambiguous": date_record.ambiguous,
                                "data": json.dumps(json_safe(date_record)),
                            }
                            for date_record in result["dates"]
                        ]
                        await session.execute(statement, date_params)
                except Exception as exc:
                    logger.warning("Could not persist legal dates: %s", exc)

                try:
                    if parsed.tables:
                        statement = text(
                            "INSERT INTO intelligence.legal_tables "
                            "(table_id, organization_id, case_id, document_id, version_id, "
                            "    extraction_id, page, caption, table_data) "
                            "VALUES (:table_id, :org, :case_id, :doc, :version, "
                            ":extraction, :page, "
                            "    :caption, CAST(:data AS jsonb))"
                        )
                        table_params = [
                            {
                                "table_id": table.table_id,
                                "org": organization_id,
                                "case_id": UUID(parsed.case_id),
                                "doc": document_id,
                                "version": version_id,
                                "extraction": extraction.extraction_id,
                                "page": table.page,
                                "caption": table.caption,
                                "data": json.dumps(json_safe(table)),
                            }
                            for table in parsed.tables
                        ]
                        await session.execute(statement, table_params)
                except Exception as exc:
                    logger.warning("Could not persist legal tables: %s", exc)
                run.processing_status = "completed"
                run.completed_at = datetime.now(UTC).replace(tzinfo=None)
                run.error_message = None
                run.processing_metadata = {
                    **(run.processing_metadata or {}),
                    "state": "indexed",
                    "chunks": len(result["chunks"]),
                    "embedded_chunks": len(vectors),
                    "pages": len(parsed.pages),
                    "definitions": len(result["definitions"]),
                    "cross_references": len(result["cross_references"]),
                    "tables": len(parsed.tables),
                    "embedding_model": "BAAI/bge-m3",
                    "embedding_dimension": 1024,
                }

    async def mark_failed(self, payload: dict[str, Any], error: Exception) -> None:
        factory = self.database.session_factory
        if factory is None:
            return
        async with factory() as session:
            async with session.begin():
                run = await ProcessingRepository(session).get_run(
                    UUID(payload["processing_run_id"]), UUID(payload["organization_id"])
                )
                if run is not None and run.processing_status != "completed":
                    run.processing_status = "failed"
                    run.completed_at = datetime.now(UTC).replace(tzinfo=None)
                    run.error_message = f"{type(error).__name__}: {error}"[:2000]
                    run.processing_metadata = {**(run.processing_metadata or {}), "state": "failed"}

    # ------------------------------------------------------------------
    # Retrieval (prototype Components 10-18 against the Cicero schema)
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_document_ids(raw: Any) -> list[str]:
        if not raw:
            return []
        values = raw if isinstance(raw, (list, tuple)) else [raw]
        ids: list[str] = []
        for value in values[:20]:
            try:
                ids.append(str(UUID(str(value))))
            except (ValueError, AttributeError, TypeError):
                raise ValueError("document_ids must contain UUID values") from None
        return ids

    def _model_runtime(self, tokenizer: str) -> ModelRuntimeMetadata:
        return ModelRuntimeMetadata(
            embedding_model_used=(
                self.embedder.model_version if self.embedder else "BAAI/bge-m3 (unloaded)"
            ),
            reranker_model_used=(
                self.reranker.model_version
                if self.reranker
                else "BAAI/bge-reranker-v2-m3 (unloaded)"
            ),
            tokenizer_used=tokenizer,
            database_backend="PostgreSQL + pgvector (Cloud SQL)",
            lexical_search_backend="PostgreSQL FTS (english)",
            simulation_mode_enabled=False,
            model_init_status="CPU worker: BGE-M3 embedder + BGE reranker",
        )

    @staticmethod
    def _insufficient_pack(
        *,
        exec_id: str,
        plan: Any,
        retrieval_meta: dict[str, Any],
        diagnostics: QueryDiagnostics,
        runtime_meta: ModelRuntimeMetadata,
        unresolved_terms: list[str],
        unresolved_refs: list[str],
        external_hints: list[str],
    ) -> dict[str, Any]:
        return EvidencePack(
            execution_id=exec_id,
            org_id=plan.org_id,
            case_id=plan.case_id,
            query=plan.query,
            query_type=plan.query_type,
            evidence=[],
            retrieval_metadata=retrieval_meta,
            insufficient_evidence=True,
            model_runtime=runtime_meta,
            diagnostics=diagnostics,
            message="Insufficient evidence found.",
            external_research_hints=list(dict.fromkeys(external_hints)),
            unresolved_terms=list(dict.fromkeys(unresolved_terms)),
            unresolved_references=list(dict.fromkeys(unresolved_refs)),
        ).to_dict()

    async def retrieve(self, payload: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        await asyncio.to_thread(self._load_retrieval_components)
        assert self.embedder is not None and self.reranker is not None
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("query must not be empty")
        organization_id = UUID(str(payload["organization_id"]))
        case_id = UUID(str(payload["case_id"]))
        try:
            top_k = max(1, min(int(payload.get("top_k", 8)), 20))
        except (TypeError, ValueError):
            raise ValueError("top_k must be an integer") from None
        try:
            token_budget = max(500, min(int(payload.get("token_budget", 3000)), 12000))
        except (TypeError, ValueError):
            raise ValueError("token_budget must be an integer") from None
        target_document_ids = self._coerce_document_ids(payload.get("document_ids"))

        ablation = payload.get("ablation") or {}
        include_dense = bool(ablation.get("dense", True))
        include_lexical = bool(ablation.get("lexical", True))
        include_exact = bool(ablation.get("exact", True))
        include_reranker = bool(ablation.get("reranker", True))
        full_mode = include_dense and include_lexical and include_exact and include_reranker

        factory = self.database.session_factory
        assert factory is not None
        org_str, case_str = str(organization_id), str(case_id)
        exec_id = f"EXEC_{uuid4().hex[:8]}"
        plan = self.router.route(
            query,
            case_str,
            org_str,
            target_document_ids=target_document_ids or None,
            token_budget=token_budget,
        )
        plan.top_k_rerank = top_k
        diagnostics = QueryDiagnostics(
            query_classification=plan.query_type,
            retrieval_route_selected=plan.query_type,
        )
        runtime_meta = self._model_runtime("BAAI/bge-m3")
        retrieval_meta: dict[str, Any] = {
            "ablation_mode": "full" if full_mode else "partial",
            "routed_query_type": plan.query_type,
            "effective_route": plan.query_type,
            "dense_candidates": 0,
            "lexical_candidates": 0,
            "sparse_candidates": 0,
            "reranked_candidates": 0,
            "embedding_model": "BAAI/bge-m3",
            "reranker_model": "BAAI/bge-reranker-v2-m3",
            "database_backend": "PostgreSQL + pgvector",
            "lexical_search_backend": "PostgreSQL FTS",
            "channels": {
                "dense": include_dense,
                "lexical": include_lexical,
                "exact": include_exact,
                "reranker": include_reranker,
            },
            "exact_identifiers": extract_legal_identifiers(query),
        }

        matched_items: list[EvidenceItem] = []
        raw_table_items: list[EvidenceItem] = []
        unresolved_terms: list[str] = []
        unresolved_refs: list[str] = []
        external_hints: list[str] = []

        async with factory() as session:
            version_ids = await self._latest_version_ids(
                session, organization_id, case_id, target_document_ids
            )
            qtype = plan.query_type

            if qtype == "exact_clause" and plan.target_clause_label:
                matched_items = await self._route_exact_clause(
                    session, plan, organization_id, case_id, version_ids
                )
                if not matched_items:
                    matched_items = await self._route_exact_identifiers(
                        session, plan.target_clause_label, organization_id, case_id, version_ids
                    )
            elif qtype == "defined_term" and plan.target_defined_term:
                matched_items, missing = await self._route_defined_term(
                    session, plan, organization_id, case_id, version_ids
                )
                unresolved_terms.extend(missing)
            elif qtype == "cross_reference" and plan.target_xref_label:
                matched_items, missing = await self._route_cross_reference(
                    session, plan, organization_id, case_id, version_ids
                )
                unresolved_refs.extend(missing)
            elif qtype == "metadata_temporal":
                matched_items = await self._route_temporal(
                    session, plan, organization_id, case_id, version_ids
                )
            elif qtype == "table_lookup":
                raw_table_items = await self._route_table_lookup(
                    session, plan, organization_id, case_id, version_ids
                )

            if qtype in ("semantic", "multi_doc_comparison") or (
                not matched_items and not raw_table_items
            ):
                selected, sem_meta = await self._semantic_candidates(
                    session,
                    plan,
                    organization_id,
                    case_id,
                    version_ids,
                    include_dense=include_dense,
                    include_lexical=include_lexical,
                    include_exact=include_exact,
                    include_reranker=include_reranker,
                )
                retrieval_meta["dense_candidates"] = sem_meta["dense_count"]
                retrieval_meta["lexical_candidates"] = sem_meta["lexical_count"]
                retrieval_meta["sparse_candidates"] = sem_meta["lexical_count"]
                diagnostics.dense_candidates.extend(sem_meta["dense_diag"])
                diagnostics.lexical_candidates.extend(sem_meta["lexical_diag"])
                diagnostics.exact_identifier_matches.extend(sem_meta["exact_diag"])
                diagnostics.rrf_results.extend(sem_meta["rrf_diag"])
                diagnostics.reranker_scores.extend(sem_meta["reranker_diag"])

                table_cache: dict[tuple[str, str], dict[str, Any] | None] = {}
                for cand in selected:
                    pl = cand["payload"]
                    sc = float(
                        cand.get("rerank_score", cand.get("rrf_score", cand.get("score", 0.0)))
                    )
                    diagnostics.final_selected_chunks.append(pl["chunk_db_id"])
                    if pl["chunk_type"] == "table_summary":
                        raw_item = await self._resolve_table_summary(
                            session, pl, organization_id, case_id, table_cache
                        )
                        if raw_item is not None:
                            raw_table_items.append(raw_item)
                        continue
                    item = self._evidence_from_payload(pl, why="matched", score=sc)
                    if pl.get("table_id"):
                        table_row = await self._fetch_table_row_by_id(
                            session,
                            organization_id,
                            UUID(pl["version_id"]),
                            str(pl["table_id"]),
                            table_cache,
                        )
                        if table_row is not None:
                            item.table_cell_references = self._table_cell_refs(
                                table_row["table_data"],
                                int(pl["char_start"]),
                                int(pl["char_end"]),
                            )
                    matched_items.append(item)

            retrieval_meta["reranked_candidates"] = len(matched_items) + len(raw_table_items)

            if not matched_items and not raw_table_items:
                retrieval_meta["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
                return self._insufficient_pack(
                    exec_id=exec_id,
                    plan=plan,
                    retrieval_meta=retrieval_meta,
                    diagnostics=diagnostics,
                    runtime_meta=runtime_meta,
                    unresolved_terms=unresolved_terms,
                    unresolved_refs=unresolved_refs,
                    external_hints=external_hints,
                )

            parent_items: list[EvidenceItem] = []
            definition_items: list[EvidenceItem] = []
            xref_items: list[EvidenceItem] = []
            if full_mode:
                used_by_matched = sum(it.token_count for it in matched_items)
                parent_items = await self._expand_parents(
                    session,
                    matched_items,
                    organization_id,
                    remaining_budget=max(0, token_budget - used_by_matched),
                )
                diagnostics.parent_expansion_nodes = [p.node_id for p in parent_items]
                definition_items, injected_terms = await self._inject_definitions(
                    session,
                    matched_items + parent_items,
                    organization_id,
                    case_id,
                    version_ids,
                )
                diagnostics.definition_injection_terms = injected_terms
                xref_items, ext_hints, unres_refs, xref_log = await self._resolve_cross_references(
                    session, matched_items, organization_id, case_id, version_ids
                )
                diagnostics.cross_reference_resolutions = xref_log
                external_hints.extend(ext_hints)
                unresolved_refs.extend(unres_refs)

            packed_items, pack_stats = pack_context(
                matched_chunks=matched_items,
                definitions=definition_items,
                parents=parent_items,
                cross_refs=xref_items,
                raw_tables=raw_table_items,
                token_budget=token_budget,
            )
            retrieval_meta.update(pack_stats)

            involved_docs = list({it.document_id for it in packed_items})
            views, tokenizer = await self._build_doc_views(
                session, organization_id, version_ids, involved_docs
            )
            runtime_meta = self._model_runtime(tokenizer)
            validator = EvidenceValidator(views.get)
            verified_items, rejections = validator.validate_evidence_list(
                packed_items,
                requested_case_id=case_str,
                requested_org_id=org_str,
                token_budget=token_budget,
            )
            retrieval_meta["validation_rejections"] = len(rejections)
            retrieval_meta["latency_ms"] = round((time.perf_counter() - t0) * 1000.0, 2)
            diagnostics.rejected_evidence_items = rejections
            diagnostics.final_context_composition = {
                "matched": sum(1 for e in verified_items if e.why_included == "matched"),
                "definition": sum(1 for e in verified_items if e.why_included == "definition"),
                "parent_or_sibling": sum(
                    1 for e in verified_items if e.why_included in ("parent", "sibling_context")
                ),
                "cross_reference": sum(
                    1 for e in verified_items if e.why_included == "cross_reference"
                ),
                "raw_table": sum(1 for e in verified_items if e.why_included == "raw_table"),
                "total_verified": len(verified_items),
                "total_rejected": len(rejections),
            }

            if not verified_items:
                return self._insufficient_pack(
                    exec_id=exec_id,
                    plan=plan,
                    retrieval_meta=retrieval_meta,
                    diagnostics=diagnostics,
                    runtime_meta=runtime_meta,
                    unresolved_terms=unresolved_terms,
                    unresolved_refs=unresolved_refs,
                    external_hints=external_hints,
                )

            for item in verified_items:
                item.derived_annotations = {
                    k: v
                    for k, v in item.derived_annotations.items()
                    if not k.startswith("_")
                }

            return EvidencePack(
                execution_id=exec_id,
                org_id=org_str,
                case_id=case_str,
                query=query,
                query_type=plan.query_type,
                evidence=verified_items,
                retrieval_metadata=retrieval_meta,
                insufficient_evidence=False,
                model_runtime=runtime_meta,
                diagnostics=diagnostics,
                message="Evidence successfully retrieved and verified.",
                external_research_hints=list(dict.fromkeys(external_hints)),
                unresolved_terms=list(dict.fromkeys(unresolved_terms)),
                unresolved_references=list(dict.fromkeys(unresolved_refs)),
            ).to_dict()

    # ------------------------------------------------------------------
    # Retrieval helpers
    # ------------------------------------------------------------------

    async def _latest_version_ids(
        self,
        session: Any,
        organization_id: UUID,
        case_id: UUID,
        document_ids: list[str],
    ) -> list[UUID]:
        """Latest version of every active document in the case (never stale versions)."""
        sql = (
            "SELECT dv.version_id FROM documents.document_versions dv "
            "JOIN documents.documents d ON d.document_id = dv.document_id "
            "AND d.organization_id = dv.organization_id "
            "WHERE dv.organization_id = :org AND d.case_id = :case AND d.status = 'active' "
            "AND dv.version_number = (SELECT MAX(dv2.version_number) "
            "FROM documents.document_versions dv2 "
            "WHERE dv2.document_id = dv.document_id "
            "AND dv2.organization_id = dv.organization_id)"
        )
        params: dict[str, Any] = {"org": organization_id, "case": case_id}
        if document_ids:
            sql += " AND dv.document_id = ANY(:docs)"
            params["docs"] = [UUID(d) for d in document_ids]
        rows = await session.execute(text(sql), params)
        return [row[0] for row in rows.all()]

    @staticmethod
    def _chunk_payload(row: Any, *, org: str, case: str) -> dict[str, Any]:
        meta = row.get("chunk_metadata") or {}
        if isinstance(meta, str):
            meta = json.loads(meta)
        return {
            "document_id": str(row["document_id"]),
            "version_id": str(row["version_id"]),
            "extraction_id": str(row["extraction_id"]),
            "case_id": case,
            "org_id": org,
            "node_id": meta.get("node_id") or "",
            "clause_label": meta.get("clause_label") or "",
            "chunk_db_id": str(row["chunk_id"]),
            "argon_chunk_id": meta.get("chunk_key") or "",
            "clean_text": row["content"],
            "embedding_text": row.get("embedding_text") or row["content"],
            "page": row["page_start"],
            "char_start": row["start_char"],
            "char_end": row["end_char"],
            "chunk_type": row["chunk_type"],
            "section_path": row.get("section_path") or [],
            "token_count": row.get("token_count") or 0,
            "table_id": meta.get("table_id"),
            "parent_id": meta.get("parent_id") or row.get("parent_chunk_key"),
            "retrieval_aid_only": bool(meta.get("retrieval_aid_only")),
            "filename": row.get("original_filename") or "",
        }

    def _evidence_from_payload(
        self, payload: dict[str, Any], *, why: str, score: float
    ) -> EvidenceItem:
        return EvidenceItem(
            evidence_id="",
            document_id=payload["document_id"],
            case_id=payload["case_id"],
            org_id=payload["org_id"],
            node_id=payload["node_id"],
            chunk_id=payload["chunk_db_id"],
            page=payload["page"],
            char_start=payload["char_start"],
            char_end=payload["char_end"],
            original_source_text=payload["clean_text"],
            extracted_text=payload["clean_text"],
            why_included=why,
            validation_status=ValidationStatus.PENDING,
            clause_label=payload["clause_label"],
            score=round(score, 4),
            token_count=payload["token_count"] or estimate_tokens(payload["clean_text"]),
            table_id=payload.get("table_id"),
            derived_annotations={
                "_version_id": payload["version_id"],
                "_parent_id": payload.get("parent_id") or "",
                "filename": payload.get("filename", ""),
                "section_path": payload.get("section_path") or [],
            },
        )

    def _evidence_from_node(
        self,
        node_data: dict[str, Any],
        document_id: str,
        *,
        org: str,
        case: str,
        why: str,
        score: float,
    ) -> EvidenceItem:
        text_value = node_data.get("text") or ""
        return EvidenceItem(
            evidence_id="",
            document_id=str(document_id),
            case_id=case,
            org_id=org,
            node_id=node_data.get("node_id") or "",
            page=node_data.get("page_start"),
            char_start=node_data.get("char_start"),
            char_end=node_data.get("char_end"),
            original_source_text=text_value,
            extracted_text=text_value,
            why_included=why,
            validation_status=ValidationStatus.PENDING,
            clause_label=node_data.get("label") or "",
            score=round(score, 4),
            token_count=estimate_tokens(text_value),
        )

    async def _fetch_clause_chunk(
        self, session: Any, organization_id: UUID, version_id: UUID, node_id: str
    ) -> Any | None:
        rows = await session.execute(
            text(
                "SELECT dc.chunk_id, dc.document_id, dc.version_id, dc.extraction_id, dc.content, "
                "dc.embedding_text, dc.page_start, dc.start_char, dc.end_char, dc.chunk_type, "
                "dc.section_path, dc.chunk_metadata, dc.parent_chunk_key, dc.token_count, "
                "dv.original_filename "
                "FROM documents.document_chunks dc "
                "JOIN documents.document_versions dv ON dv.version_id = dc.version_id "
                "AND dv.organization_id = dc.organization_id "
                "WHERE dc.organization_id = :org AND dc.version_id = :version "
                "AND dc.chunk_metadata->>'node_id' = :node "
                "ORDER BY CASE WHEN dc.chunk_type = 'clause' THEN 0 "
                "WHEN dc.chunk_type = 'parent_section' THEN 1 ELSE 2 END, dc.chunk_index LIMIT 1"
            ),
            {"org": organization_id, "version": version_id, "node": node_id},
        )
        return rows.mappings().first()

    async def _fetch_parent_chunk(
        self, session: Any, organization_id: UUID, version_id: UUID, node_id: str
    ) -> Any | None:
        rows = await session.execute(
            text(
                "SELECT dc.chunk_id, dc.document_id, dc.version_id, dc.extraction_id, dc.content, "
                "dc.embedding_text, dc.page_start, dc.start_char, dc.end_char, dc.chunk_type, "
                "dc.section_path, dc.chunk_metadata, dc.parent_chunk_key, dc.token_count, "
                "dv.original_filename "
                "FROM documents.document_chunks dc "
                "JOIN documents.document_versions dv ON dv.version_id = dc.version_id "
                "AND dv.organization_id = dc.organization_id "
                "WHERE dc.organization_id = :org AND dc.version_id = :version "
                "AND dc.chunk_type = 'parent_section' "
                "AND dc.chunk_metadata->>'node_id' = :node LIMIT 1"
            ),
            {"org": organization_id, "version": version_id, "node": node_id},
        )
        return rows.mappings().first()

    async def _fetch_node_row(
        self,
        session: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
        node_id: str,
        document_id: UUID | None = None,
    ) -> Any | None:
        if not version_ids:
            return None
        sql = (
            "SELECT node_id, document_id, version_id, extraction_id, parent_node_id, node_data "
            "FROM intelligence.legal_hierarchy_nodes "
            "WHERE organization_id = :org AND case_id = :case "
            "AND version_id = ANY(:vids) AND node_id = :node"
        )
        params: dict[str, Any] = {
            "org": organization_id,
            "case": case_id,
            "vids": version_ids,
            "node": node_id,
        }
        if document_id is not None:
            sql += " AND document_id = :doc"
            params["doc"] = document_id
        rows = await session.execute(text(sql + " LIMIT 1"), params)
        return rows.mappings().first()

    async def _fetch_definitions(
        self,
        session: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
        document_id: UUID,
    ) -> list[Any]:
        if not version_ids:
            return []
        rows = await session.execute(
            text(
                "SELECT term, verbatim_definition, normalized_meaning, document_id, page, "
                "char_start, char_end, definition_data "
                "FROM intelligence.legal_definitions "
                "WHERE organization_id = :org AND case_id = :case "
                "AND version_id = ANY(:vids) AND document_id = :doc "
                "ORDER BY length(term) DESC"
            ),
            {"org": organization_id, "case": case_id, "vids": version_ids, "doc": document_id},
        )
        return list(rows.mappings().all())

    async def _fetch_raw_tables(
        self,
        session: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
        document_id: UUID | None = None,
        table_id: str | None = None,
    ) -> list[Any]:
        if not version_ids:
            return []
        sql = (
            "SELECT table_id, document_id, version_id, page, caption, table_data "
            "FROM intelligence.legal_tables "
            "WHERE organization_id = :org AND case_id = :case AND version_id = ANY(:vids)"
        )
        params: dict[str, Any] = {"org": organization_id, "case": case_id, "vids": version_ids}
        if document_id is not None:
            sql += " AND document_id = :doc"
            params["doc"] = document_id
        if table_id is not None:
            sql += " AND table_id = :tid"
            params["tid"] = table_id
        rows = await session.execute(text(sql), params)
        return list(rows.mappings().all())

    async def _fetch_table_row_by_id(
        self,
        session: Any,
        organization_id: UUID,
        version_id: UUID,
        table_id: str,
        cache: dict[tuple[str, str], dict[str, Any] | None],
    ) -> dict[str, Any] | None:
        key = (str(version_id), table_id)
        if key in cache:
            return cache[key]
        rows = await session.execute(
            text(
                "SELECT table_id, document_id, version_id, page, caption, table_data "
                "FROM intelligence.legal_tables "
                "WHERE organization_id = :org AND version_id = :version AND table_id = :tid LIMIT 1"
            ),
            {"org": organization_id, "version": version_id, "tid": table_id},
        )
        row = rows.mappings().first()
        result = dict(row) if row is not None else None
        cache[key] = result
        return result

    @staticmethod
    def _table_cell_refs(table_data: Any, char_start: int, char_end: int) -> list[dict[str, Any]]:
        data = table_data if isinstance(table_data, dict) else {}
        cells = data.get("cells") or []
        return [
            {
                "row_index": c.get("row_index"),
                "col_index": c.get("col_index"),
                "row_identifier": c.get("row_identifier"),
                "col_header": c.get("col_header"),
                "raw_cell_value": c.get("raw_cell_value"),
            }
            for c in cells
            if isinstance(c, dict)
            and c.get("char_start") is not None
            and c.get("char_end") is not None
            and int(c["char_start"]) >= char_start
            and int(c["char_end"]) <= char_end
        ]

    async def _build_doc_views(
        self,
        session: Any,
        organization_id: UUID,
        version_ids: list[UUID],
        document_ids: list[str],
    ) -> tuple[dict[str, ParsedDocView], str]:
        views: dict[str, ParsedDocView] = {}
        tokenizer = "BAAI/bge-m3"
        if not version_ids or not document_ids:
            return views, tokenizer
        doc_uuids = [UUID(d) for d in document_ids]
        ext_rows = await session.execute(
            text(
                "SELECT DISTINCT ON (de.document_id) de.document_id, de.version_id, "
                "de.extracted_text, de.extraction_metadata "
                "FROM documents.document_extractions de "
                "WHERE de.organization_id = :org AND de.version_id = ANY(:vids) "
                "AND de.document_id = ANY(:docs) "
                "ORDER BY de.document_id, de.created_at DESC"
            ),
            {"org": organization_id, "vids": version_ids, "docs": doc_uuids},
        )
        extractions = list(ext_rows.mappings().all())
        if not extractions:
            return views, tokenizer
        node_rows = await session.execute(
            text(
                "SELECT node_id, document_id, node_data FROM intelligence.legal_hierarchy_nodes "
                "WHERE organization_id = :org AND version_id = ANY(:vids) "
                "AND document_id = ANY(:docs)"
            ),
            {"org": organization_id, "vids": version_ids, "docs": doc_uuids},
        )
        nodes_by_doc: dict[str, dict[str, dict[str, Any]]] = {}
        for row in node_rows.mappings().all():
            data = row["node_data"] if isinstance(row["node_data"], dict) else {}
            entry = dict(data)
            entry["document_id"] = str(row["document_id"])
            nodes_by_doc.setdefault(str(row["document_id"]), {})[str(row["node_id"])] = entry
        table_rows = await session.execute(
            text(
                "SELECT table_id, document_id, page, table_data FROM intelligence.legal_tables "
                "WHERE organization_id = :org AND version_id = ANY(:vids) "
                "AND document_id = ANY(:docs)"
            ),
            {"org": organization_id, "vids": version_ids, "docs": doc_uuids},
        )
        tables_by_doc: dict[str, dict[str, dict[str, Any]]] = {}
        for row in table_rows.mappings().all():
            data = row["table_data"] if isinstance(row["table_data"], dict) else {}
            tables_by_doc.setdefault(str(row["document_id"]), {})[str(row["table_id"])] = {
                "page": row["page"],
                "cells": data.get("cells") or [],
            }
        for row in extractions:
            doc_key = str(row["document_id"])
            metadata = (
                row["extraction_metadata"] if isinstance(row["extraction_metadata"], dict) else {}
            )
            if metadata.get("tokenizer"):
                tokenizer = str(metadata["tokenizer"])
            pages: dict[int, tuple[int, int]] = {}
            for page in metadata.get("pages") or []:
                if isinstance(page, dict) and page.get("page_number") is not None:
                    pages[int(page["page_number"])] = (
                        int(page.get("char_start") or 0),
                        int(page.get("char_end") or 0),
                    )
            views[doc_key] = ParsedDocView(
                document_id=doc_key,
                full_text=row["extracted_text"] or "",
                pages=pages,
                nodes=nodes_by_doc.get(doc_key, {}),
                tables=tables_by_doc.get(doc_key, {}),
            )
        return views, tokenizer

    @staticmethod
    def _as_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except ValueError:
                return {}
            return parsed if isinstance(parsed, dict) else {}
        return {}

    async def _fetch_table_chunk(
        self, session: Any, organization_id: UUID, version_id: UUID, table_id: str
    ) -> Any | None:
        rows = await session.execute(
            text(
                "SELECT dc.chunk_id, dc.document_id, dc.version_id, dc.extraction_id, dc.content, "
                "dc.embedding_text, dc.page_start, dc.start_char, dc.end_char, dc.chunk_type, "
                "dc.section_path, dc.chunk_metadata, dc.parent_chunk_key, dc.token_count, "
                "dv.original_filename "
                "FROM documents.document_chunks dc "
                "JOIN documents.document_versions dv ON dv.version_id = dc.version_id "
                "AND dv.organization_id = dc.organization_id "
                "WHERE dc.organization_id = :org AND dc.version_id = :version "
                "AND dc.chunk_metadata->>'table_id' = :tid "
                "AND dc.chunk_type IN ('table_raw', 'table_row_group') "
                "ORDER BY dc.char_start LIMIT 1"
            ),
            {"org": organization_id, "version": version_id, "tid": table_id},
        )
        return rows.mappings().first()

    async def _semantic_candidates(
        self,
        session: Any,
        plan: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
        *,
        include_dense: bool,
        include_lexical: bool,
        include_exact: bool,
        include_reranker: bool,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        assert self.embedder is not None and self.reranker is not None
        org_str, case_str = str(organization_id), str(case_id)
        query = plan.query
        chunk_types = sorted(INDEXABLE_CHUNK_TYPES | {"table_summary"})
        base_cols = (
            "dc.chunk_id, dc.document_id, dc.version_id, dc.extraction_id, dc.content, "
            "dc.embedding_text, dc.page_start, dc.start_char, dc.end_char, dc.chunk_type, "
            "dc.section_path, dc.chunk_metadata, dc.parent_chunk_key, dc.token_count, "
            "dv.original_filename "
        )
        joins = (
            "FROM documents.document_chunks dc "
            "JOIN documents.document_versions dv ON dv.version_id = dc.version_id "
            "AND dv.organization_id = dc.organization_id "
        )
        dense_list: list[dict[str, Any]] = []
        lexical_list: list[dict[str, Any]] = []
        exact_diag: list[dict[str, Any]] = []

        if include_dense and version_ids:
            encoded = await asyncio.to_thread(self.embedder.encode_batch, [query], batch_size=1)
            vec = encoded["dense_vecs"][0]
            vector_text = "[" + ",".join(f"{float(v):.8f}" for v in vec) + "]"
            rows = await session.execute(
                text(
                    f"SELECT {base_cols}, (dc.embedding <=> CAST(:vec AS vector)) AS distance "
                    f"{joins}"
                    "WHERE dc.organization_id = :org AND dc.version_id = ANY(:vids) "
                    "AND dc.embedding IS NOT NULL AND dc.page_start IS NOT NULL "
                    "AND dc.chunk_type = ANY(:types) "
                    "ORDER BY dc.embedding <=> CAST(:vec AS vector) LIMIT 50"
                ),
                {
                    "vec": vector_text,
                    "org": organization_id,
                    "vids": version_ids,
                    "types": chunk_types,
                },
            )
            dense_list = [
                {
                    "chunk_id": str(r["chunk_id"]),
                    "score": float(1.0 - float(r["distance"])),
                    "payload": self._chunk_payload(r, org=org_str, case=case_str),
                }
                for r in rows.mappings().all()
            ]

        if include_lexical and version_ids:
            rows = await session.execute(
                text(
                    f"SELECT {base_cols}, "
                    "ts_rank_cd(dc.search_vector, "
                    "websearch_to_tsquery('english', :query)) AS score "
                    f"{joins}"
                    "WHERE dc.organization_id = :org AND dc.version_id = ANY(:vids) "
                    "AND dc.chunk_type = ANY(:types) "
                    "AND dc.search_vector @@ websearch_to_tsquery('english', :query) "
                    "ORDER BY score DESC LIMIT 50"
                ),
                {
                    "org": organization_id,
                    "vids": version_ids,
                    "types": chunk_types,
                    "query": query,
                },
            )
            lexical_list = [
                {
                    "chunk_id": str(r["chunk_id"]),
                    "score": float(r["score"]),
                    "payload": self._chunk_payload(r, org=org_str, case=case_str),
                }
                for r in rows.mappings().all()
            ]
            if include_exact:
                identifiers = extract_legal_identifiers(query)
                if identifiers:
                    exact_rows = await session.execute(
                        text(
                            f"SELECT {base_cols} {joins}"
                            "WHERE dc.organization_id = :org AND dc.version_id = ANY(:vids) "
                            "AND dc.chunk_type = ANY(:types) "
                            "AND dc.legal_identifiers && CAST(:identifiers AS text[]) "
                            "ORDER BY dc.page_start NULLS LAST LIMIT 50"
                        ),
                        {
                            "org": organization_id,
                            "vids": version_ids,
                            "types": chunk_types,
                            "identifiers": identifiers,
                        },
                    )
                    exact_hits = [
                        {
                            "chunk_id": str(r["chunk_id"]),
                            "score": 1.0,
                            "payload": self._chunk_payload(r, org=org_str, case=case_str),
                        }
                        for r in exact_rows.mappings().all()
                    ]
                    exact_diag = [
                        {
                            "chunk_id": h["chunk_id"],
                            "clause_label": h["payload"]["clause_label"],
                            "score": h["score"],
                        }
                        for h in exact_hits[:10]
                    ]
                    by_id = {h["chunk_id"]: h for h in lexical_list}
                    for ex in exact_hits:
                        if ex["chunk_id"] in by_id:
                            by_id[ex["chunk_id"]]["score"] = round(
                                by_id[ex["chunk_id"]]["score"] + ex["score"], 4
                            )
                        else:
                            lexical_list.append(dict(ex))
                    lexical_list.sort(key=lambda x: x["score"], reverse=True)
                    lexical_list = lexical_list[:50]

        dense_diag = [
            {
                "rank": i + 1,
                "chunk_id": r["chunk_id"],
                "clause_label": r["payload"].get("clause_label", ""),
                "score": round(r["score"], 4),
            }
            for i, r in enumerate(dense_list[:15])
        ]
        lexical_diag = [
            {
                "rank": i + 1,
                "chunk_id": r["chunk_id"],
                "clause_label": r["payload"].get("clause_label", ""),
                "score": round(r["score"], 4),
            }
            for i, r in enumerate(lexical_list[:15])
        ]
        if dense_list or lexical_list:
            fused = reciprocal_rank_fusion(dense_list, lexical_list)
        else:
            fused = []
        rrf_diag = [
            {
                "rank": i + 1,
                "chunk_id": f["chunk_id"],
                "clause_label": f["payload"].get("clause_label", ""),
                "dense_rank": f["dense_rank"],
                "lexical_rank": f["lexical_rank"],
                "rrf_score": f["rrf_score"],
            }
            for i, f in enumerate(fused[:15])
        ]
        reranker_diag: list[dict[str, Any]] = []
        if include_reranker and fused:
            cands = [
                {
                    "chunk_id": f["chunk_id"],
                    "payload": f["payload"],
                    "rrf_score": f["rrf_score"],
                    "score": f["score"],
                }
                for f in fused[:50]
            ]
            reranked, insuff, r_diag = await asyncio.to_thread(
                self.reranker.rerank, query, cands, top_k=plan.top_k_rerank
            )
            reranker_diag = r_diag
            selected = [] if insuff else list(reranked)
        else:
            selected = [dict(f) for f in fused[: plan.top_k_rerank]]
        meta = {
            "dense_count": len(dense_list),
            "lexical_count": len(lexical_list),
            "dense_diag": dense_diag,
            "lexical_diag": lexical_diag,
            "exact_diag": exact_diag,
            "rrf_diag": rrf_diag,
            "reranker_diag": reranker_diag,
        }
        return selected, meta

    # ------------------------------------------------------------------
    # Deterministic routes (prototype Components 10/13-15)
    # ------------------------------------------------------------------

    @staticmethod
    def _label_variants(label: str) -> tuple[list[str], list[str]]:
        base = label.strip().lower()
        variants = {base}
        if not base.startswith(("article ", "schedule ", "annexure ")):
            variants |= {f"section {base}", f"clause {base}"}
        raws = set(extract_legal_identifiers(label)) | {base}
        return sorted(variants), sorted(raws)

    async def _route_exact_clause(
        self,
        session: Any,
        plan: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> list[EvidenceItem]:
        label = (plan.target_clause_label or "").strip()
        if not label or not version_ids:
            return []
        labels, raws = self._label_variants(label)
        rows = await session.execute(
            text(
                "SELECT node_id, document_id, version_id, node_data "
                "FROM intelligence.legal_hierarchy_nodes "
                "WHERE organization_id = :org AND case_id = :case AND version_id = ANY(:vids) "
                "AND (lower(label) = ANY(:labels) "
                "OR lower(node_data->>'raw_number') = ANY(:raws))"
            ),
            {
                "org": organization_id,
                "case": case_id,
                "vids": version_ids,
                "labels": labels,
                "raws": raws,
            },
        )
        items: list[EvidenceItem] = []
        for row in rows.mappings().all():
            chunk = await self._fetch_clause_chunk(
                session, organization_id, row["version_id"], str(row["node_id"])
            )
            if chunk is not None:
                items.append(
                    self._evidence_from_payload(
                        self._chunk_payload(chunk, org=str(organization_id), case=str(case_id)),
                        why="matched",
                        score=1.0,
                    )
                )
            else:
                items.append(
                    self._evidence_from_node(
                        self._as_dict(row["node_data"]),
                        str(row["document_id"]),
                        org=str(organization_id),
                        case=str(case_id),
                        why="matched",
                        score=1.0,
                    )
                )
        return items

    async def _route_exact_identifiers(
        self,
        session: Any,
        identifier_query: str,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> list[EvidenceItem]:
        identifiers = extract_legal_identifiers(identifier_query)
        if not identifiers or not version_ids:
            return []
        rows = await session.execute(
            text(
                "SELECT dc.chunk_id, dc.document_id, dc.version_id, dc.extraction_id, dc.content, "
                "dc.embedding_text, dc.page_start, dc.start_char, dc.end_char, dc.chunk_type, "
                "dc.section_path, dc.chunk_metadata, dc.parent_chunk_key, dc.token_count, "
                "dv.original_filename "
                "FROM documents.document_chunks dc "
                "JOIN documents.document_versions dv ON dv.version_id = dc.version_id "
                "AND dv.organization_id = dc.organization_id "
                "WHERE dc.organization_id = :org AND dc.version_id = ANY(:vids) "
                "AND dc.chunk_type = ANY(:types) "
                "AND dc.legal_identifiers && CAST(:identifiers AS text[]) "
                "ORDER BY dc.page_start NULLS LAST LIMIT 50"
            ),
            {
                "org": organization_id,
                "vids": version_ids,
                "types": sorted(INDEXABLE_CHUNK_TYPES),
                "identifiers": identifiers,
            },
        )
        return [
            self._evidence_from_payload(
                self._chunk_payload(r, org=str(organization_id), case=str(case_id)),
                why="matched",
                score=1.0,
            )
            for r in rows.mappings().all()
        ]

    async def _route_defined_term(
        self,
        session: Any,
        plan: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> tuple[list[EvidenceItem], list[str]]:
        term = (plan.target_defined_term or "").strip()
        if not term or not version_ids:
            return [], [term] if term else []
        rows = await session.execute(
            text(
                "SELECT term, verbatim_definition, normalized_meaning, document_id, page, "
                "char_start, char_end, definition_data "
                "FROM intelligence.legal_definitions "
                "WHERE organization_id = :org AND case_id = :case AND version_id = ANY(:vids) "
                "AND (lower(term) = lower(:term) "
                "OR lower(:term) LIKE '%' || lower(term) || '%') "
                "ORDER BY length(term) DESC LIMIT 20"
            ),
            {"org": organization_id, "case": case_id, "vids": version_ids, "term": term},
        )
        items: list[EvidenceItem] = []
        for row in rows.mappings().all():
            if row["page"] is None or row["char_start"] is None or row["char_end"] is None:
                continue
            data = self._as_dict(row["definition_data"])
            definition_text = row["verbatim_definition"] or ""
            items.append(
                EvidenceItem(
                    evidence_id="",
                    document_id=str(row["document_id"]),
                    case_id=str(case_id),
                    org_id=str(organization_id),
                    node_id=data.get("node_id") or "",
                    page=row["page"],
                    char_start=row["char_start"],
                    char_end=row["char_end"],
                    original_source_text=definition_text,
                    extracted_text=row["normalized_meaning"] or definition_text,
                    why_included="matched",
                    validation_status=ValidationStatus.PENDING,
                    clause_label=f"Def:{row['term']}",
                    score=1.0,
                    token_count=estimate_tokens(definition_text),
                    derived_annotations={
                        "defined_term": row["term"],
                        "pattern_type": data.get("pattern_type"),
                    },
                )
            )
        return items, ([] if items else [term])

    async def _route_cross_reference(
        self,
        session: Any,
        plan: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> tuple[list[EvidenceItem], list[str]]:
        label = (plan.target_xref_label or "").strip()
        if not label or not version_ids:
            return [], [label] if label else []
        labels, _raws = self._label_variants(label)
        rows = await session.execute(
            text(
                "SELECT from_node_id, to_node_id, target_label, normalized_reference, "
                "resolution_status, document_id, version_id, edge_data "
                "FROM intelligence.legal_cross_references "
                "WHERE organization_id = :org AND case_id = :case AND version_id = ANY(:vids) "
                "AND (lower(target_label) = ANY(:labels) "
                "OR lower(normalized_reference) = ANY(:labels)) "
                "AND (:rtype IS NULL OR edge_data->>'type' = :rtype) LIMIT 50"
            ),
            {
                "org": organization_id,
                "case": case_id,
                "vids": version_ids,
                "labels": labels,
                "rtype": plan.target_xref_type,
            },
        )
        items: list[EvidenceItem] = []
        for edge in rows.mappings().all():
            node_row = await self._fetch_node_row(
                session,
                organization_id,
                case_id,
                version_ids,
                str(edge["from_node_id"]),
                edge["document_id"],
            )
            if node_row is None:
                continue
            chunk = await self._fetch_clause_chunk(
                session, organization_id, edge["version_id"], str(edge["from_node_id"])
            )
            if chunk is not None:
                items.append(
                    self._evidence_from_payload(
                        self._chunk_payload(
                            chunk, org=str(organization_id), case=str(case_id)
                        ),
                        why="matched",
                        score=1.0,
                    )
                )
            else:
                items.append(
                    self._evidence_from_node(
                        self._as_dict(node_row["node_data"]),
                        str(edge["document_id"]),
                        org=str(organization_id),
                        case=str(case_id),
                        why="matched",
                        score=1.0,
                    )
                )
        return items, ([] if items else [label])

    async def _route_temporal(
        self,
        session: Any,
        plan: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> list[EvidenceItem]:
        if not version_ids:
            return []
        sql = (
            "SELECT date_data, document_id, version_id FROM intelligence.legal_dates "
            "WHERE organization_id = :org AND case_id = :case AND version_id = ANY(:vids)"
        )
        params: dict[str, Any] = {"org": organization_id, "case": case_id, "vids": version_ids}
        if plan.date_role_filter:
            sql += " AND date_role = :role"
            params["role"] = plan.date_role_filter
        if plan.date_start_iso:
            sql += " AND normalized_date >= CAST(:start AS date)"
            params["start"] = plan.date_start_iso
        if plan.date_end_iso:
            sql += " AND normalized_date <= CAST(:end AS date)"
            params["end"] = plan.date_end_iso
        sql += " ORDER BY normalized_date NULLS LAST LIMIT 50"
        rows = await session.execute(text(sql), params)
        items: list[EvidenceItem] = []
        for row in rows.mappings().all():
            data = self._as_dict(row["date_data"])
            node_id = data.get("node_id")
            if not node_id:
                continue
            chunk = await self._fetch_clause_chunk(
                session, organization_id, row["version_id"], str(node_id)
            )
            if chunk is not None:
                item = self._evidence_from_payload(
                    self._chunk_payload(chunk, org=str(organization_id), case=str(case_id)),
                    why="matched",
                    score=1.0,
                )
            else:
                node_row = await self._fetch_node_row(
                    session,
                    organization_id,
                    case_id,
                    version_ids,
                    str(node_id),
                    row["document_id"],
                )
                if node_row is None:
                    continue
                item = self._evidence_from_node(
                    self._as_dict(node_row["node_data"]),
                    str(row["document_id"]),
                    org=str(organization_id),
                    case=str(case_id),
                    why="matched",
                    score=1.0,
                )
            item.derived_annotations.update(
                {
                    "date_iso": data.get("iso"),
                    "date_role": data.get("role"),
                    "is_derived_date": data.get("derived"),
                    "derivation_rule": data.get("derivation_rule"),
                }
            )
            items.append(item)
        return items

    async def _route_table_lookup(
        self,
        session: Any,
        plan: Any,
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> list[EvidenceItem]:
        params = plan.table_query_params or {}
        caption_hint = (params.get("caption_hint") or "").lower()
        rows = await self._fetch_raw_tables(session, organization_id, case_id, version_ids)
        items: list[EvidenceItem] = []
        for row in rows:
            if caption_hint and caption_hint not in (row["caption"] or "").lower():
                continue
            data = self._as_dict(row["table_data"])
            cells = [
                TableCellProvenance(
                    table_id=c.get("table_id") or str(row["table_id"]),
                    row_index=int(c.get("row_index") or 0),
                    col_index=int(c.get("col_index") or 0),
                    row_identifier=c.get("row_identifier") or "",
                    col_header=c.get("col_header") or "",
                    raw_cell_value=c.get("raw_cell_value") or "",
                    page=int(c.get("page") or row["page"] or 1),
                    char_start=int(c.get("char_start") or 0),
                    char_end=int(c.get("char_end") or 0),
                )
                for c in (data.get("cells") or [])
                if isinstance(c, dict)
            ]
            raw = RawTable(
                table_id=str(row["table_id"]),
                document_id=str(row["document_id"]),
                caption=row["caption"] or "",
                headers=list(data.get("headers") or []),
                rows=list(data.get("rows") or []),
                page=row["page"],
                parent_node_id=data.get("parent_node_id"),
                bbox=data.get("bbox"),
                char_start=int(data.get("char_start") or 0),
                char_end=int(data.get("char_end") or 0),
                cells=cells,
            )
            lookup = await asyncio.to_thread(
                self.table_processor.table_lookup,
                raw_table=raw,
                row_filter_col=params.get("row_filter_col"),
                row_filter_val=params.get("row_filter_val"),
                aggregation=params.get("aggregation"),
                agg_column=params.get("agg_column"),
            )
            if not lookup.get("matched_rows") and lookup.get("aggregation_value") is None:
                continue
            chunk = await self._fetch_table_chunk(
                session, organization_id, row["version_id"], str(row["table_id"])
            )
            if chunk is None:
                continue
            item = self._evidence_from_payload(
                self._chunk_payload(chunk, org=str(organization_id), case=str(case_id)),
                why="raw_table",
                score=1.0,
            )
            item.extracted_text = lookup.get("markdown_view") or item.extracted_text
            item.derived_annotations.update(lookup.get("derived_annotations") or {})
            item.table_cell_references = lookup.get("matched_cells") or []
            items.append(item)
        return items

    async def _resolve_table_summary(
        self,
        session: Any,
        payload: dict[str, Any],
        organization_id: UUID,
        case_id: UUID,
        cache: dict[tuple[str, str], dict[str, Any] | None],
    ) -> EvidenceItem | None:
        table_id = payload.get("table_id")
        if not table_id:
            return None
        version = UUID(str(payload["version_id"]))
        chunk = await self._fetch_table_chunk(
            session, organization_id, version, str(table_id)
        )
        if chunk is None:
            return None
        raw_payload = self._chunk_payload(chunk, org=str(organization_id), case=str(case_id))
        item = self._evidence_from_payload(raw_payload, why="raw_table", score=0.99)
        table_row = await self._fetch_table_row_by_id(
            session, organization_id, version, str(table_id), cache
        )
        if table_row is not None:
            item.table_cell_references = self._table_cell_refs(
                table_row["table_data"],
                int(raw_payload["char_start"]),
                int(raw_payload["char_end"]),
            )
        return item

    # ------------------------------------------------------------------
    # Context expansion (prototype Components 13-15)
    # ------------------------------------------------------------------

    async def _expand_parents(
        self,
        session: Any,
        matched_items: list[EvidenceItem],
        organization_id: UUID,
        remaining_budget: int,
    ) -> list[EvidenceItem]:
        expanded: list[EvidenceItem] = []
        seen_parents: set[str] = set()
        for item in matched_items:
            parent_id = item.derived_annotations.get("_parent_id")
            version = item.derived_annotations.get("_version_id")
            if not parent_id or not version or str(parent_id) in seen_parents:
                continue
            seen_parents.add(str(parent_id))
            parent_row = await self._fetch_parent_chunk(
                session, organization_id, UUID(str(version)), str(parent_id)
            )
            if parent_row is not None:
                payload = self._chunk_payload(
                    parent_row, org=item.org_id, case=item.case_id
                )
                tokens = payload["token_count"] or estimate_tokens(payload["clean_text"])
                if tokens <= min(800, remaining_budget):
                    expanded.append(
                        self._evidence_from_payload(
                            payload, why="parent", score=round(item.score * 0.9, 4)
                        )
                    )
                continue
            node_row = await self._fetch_node_row(
                session,
                organization_id,
                UUID(item.case_id),
                [UUID(str(version))],
                str(parent_id),
                UUID(item.document_id),
            )
            if node_row is not None:
                data = self._as_dict(node_row["node_data"])
                if data.get("text"):
                    expanded.append(
                        self._evidence_from_node(
                            data,
                            item.document_id,
                            org=item.org_id,
                            case=item.case_id,
                            why="sibling_context",
                            score=round(item.score * 0.85, 4),
                        )
                    )
        return expanded

    async def _inject_definitions(
        self,
        session: Any,
        evidence_items: list[EvidenceItem],
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> tuple[list[EvidenceItem], list[str]]:
        injected: list[EvidenceItem] = []
        labels: list[str] = []
        seen_def_keys: set[tuple[str, str]] = set()
        defs_cache: dict[str, list[Any]] = {}
        for item in evidence_items:
            doc_key = item.document_id
            if doc_key not in defs_cache:
                defs_cache[doc_key] = await self._fetch_definitions(
                    session, organization_id, case_id, version_ids, UUID(doc_key)
                )
            for d in defs_cache[doc_key]:
                key = (str(d["document_id"]), str(d["term"]).lower())
                if key in seen_def_keys:
                    continue
                data = self._as_dict(d["definition_data"])
                if data.get("node_id") == item.node_id and d["char_start"] == item.char_start:
                    seen_def_keys.add(key)
                    continue
                pattern = re.compile(r"\b" + re.escape(str(d["term"])) + r"s?\b")
                if not pattern.search(item.original_source_text):
                    continue
                seen_def_keys.add(key)
                if (
                    d["page"] is None
                    or d["char_start"] is None
                    or d["char_end"] is None
                ):
                    continue
                definition_text = d["verbatim_definition"] or ""
                labels.append(f"Def:{d['term']}")
                injected.append(
                    EvidenceItem(
                        evidence_id="",
                        document_id=str(d["document_id"]),
                        case_id=item.case_id,
                        org_id=item.org_id,
                        node_id=data.get("node_id") or "",
                        page=d["page"],
                        char_start=d["char_start"],
                        char_end=d["char_end"],
                        original_source_text=definition_text,
                        extracted_text=d["normalized_meaning"] or definition_text,
                        derived_annotations={
                            "defined_term": d["term"],
                            "pattern_type": data.get("pattern_type"),
                        },
                        why_included="definition",
                        validation_status=ValidationStatus.PENDING,
                        clause_label=f"Def:{d['term']}",
                        score=round(item.score * 0.95, 4),
                        token_count=estimate_tokens(definition_text),
                    )
                )
        return injected, labels

    async def _resolve_cross_references(
        self,
        session: Any,
        evidence_items: list[EvidenceItem],
        organization_id: UUID,
        case_id: UUID,
        version_ids: list[UUID],
    ) -> tuple[list[EvidenceItem], list[str], list[str], list[dict[str, Any]]]:
        resolved_items: list[EvidenceItem] = []
        external_hints: list[str] = []
        unresolved_refs: list[str] = []
        resolution_log: list[dict[str, Any]] = []
        visited_nodes: set[str] = {it.node_id for it in evidence_items}
        frontier: list[tuple[str, str, int, float]] = [
            (it.document_id, it.node_id, 0, it.score) for it in evidence_items
        ]

        async def outgoing(doc: str, node: str) -> list[Any]:
            if not version_ids:
                return []
            rows = await session.execute(
                text(
                    "SELECT from_node_id, to_node_id, target_label, normalized_reference, "
                    "resolution_status, document_id, version_id, edge_data "
                    "FROM intelligence.legal_cross_references "
                    "WHERE organization_id = :org AND case_id = :case "
                    "AND version_id = ANY(:vids) AND document_id = :doc "
                    "AND from_node_id = :node"
                ),
                {
                    "org": organization_id,
                    "case": case_id,
                    "vids": version_ids,
                    "doc": UUID(doc),
                    "node": node,
                },
            )
            return list(rows.mappings().all())

        while frontier:
            doc_id, curr_node_id, hop, base_score = frontier.pop(0)
            edges = await outgoing(doc_id, curr_node_id)
            curr_node = await self._fetch_node_row(
                session, organization_id, case_id, version_ids, curr_node_id, UUID(doc_id)
            )
            if curr_node is not None and curr_node["parent_node_id"]:
                edges = edges + await outgoing(doc_id, str(curr_node["parent_node_id"]))
            for edge in edges:
                edge_data = self._as_dict(edge["edge_data"])
                resolution_log.append(
                    {
                        "from_node": edge["from_node_id"],
                        "raw_text": edge_data.get("raw_text"),
                        "normalized_reference": edge["normalized_reference"],
                        "to_node": edge["to_node_id"],
                        "status": edge["resolution_status"],
                    }
                )
                if edge_data.get("is_external") and edge_data.get("external_citation"):
                    citation = str(edge_data["external_citation"])
                    if citation not in external_hints:
                        external_hints.append(citation)
                    continue
                if edge["resolution_status"] in (
                    "UNRESOLVED",
                    "AMBIGUOUS",
                ) or not edge["to_node_id"]:
                    flag = f"{edge_data.get('raw_text')} [{edge['resolution_status']}]"
                    if flag not in unresolved_refs:
                        unresolved_refs.append(flag)
                    continue
                allowed_hops = (
                    2 if edge_data.get("type") in ("notwithstanding", "subject_to") else 1
                )
                next_hop = hop + 1
                if next_hop > allowed_hops or str(edge["to_node_id"]) in visited_nodes:
                    continue
                visited_nodes.add(str(edge["to_node_id"]))
                target_node = await self._fetch_node_row(
                    session,
                    organization_id,
                    case_id,
                    version_ids,
                    str(edge["to_node_id"]),
                    edge["document_id"],
                )
                if target_node is None:
                    continue
                nodes_to_add = [target_node]
                target_data = self._as_dict(target_node["node_data"])
                if target_data.get("level") == "article":
                    for child_id in target_data.get("children_ids") or []:
                        if str(child_id) in visited_nodes:
                            continue
                        child = await self._fetch_node_row(
                            session,
                            organization_id,
                            case_id,
                            version_ids,
                            str(child_id),
                            edge["document_id"],
                        )
                        if child is not None:
                            visited_nodes.add(str(child_id))
                            nodes_to_add.append(child)
                for t_node in nodes_to_add:
                    t_data = self._as_dict(t_node["node_data"])
                    chunk = await self._fetch_clause_chunk(
                        session, organization_id, edge["version_id"], str(t_node["node_id"])
                    )
                    if chunk is not None:
                        item = self._evidence_from_payload(
                            self._chunk_payload(
                                chunk, org=str(organization_id), case=str(case_id)
                            ),
                            why="cross_reference",
                            score=round(base_score * (0.88**next_hop), 4),
                        )
                    else:
                        item = self._evidence_from_node(
                            t_data,
                            doc_id,
                            org=str(organization_id),
                            case=str(case_id),
                            why="cross_reference",
                            score=round(base_score * (0.88**next_hop), 4),
                        )
                    resolved_items.append(item)
                    frontier.append((doc_id, str(t_node["node_id"]), next_hop, base_score))

        return resolved_items, external_hints, unresolved_refs, resolution_log


def verify_pubsub_identity(authorization: str | None, settings: Settings) -> None:
    """Validate the OIDC identity token configured on the Pub/Sub push subscription."""
    audience = settings.pubsub_push_audience
    expected_email = settings.pubsub_push_service_account
    if not audience or not expected_email:
        raise HTTPException(status_code=503, detail="Pub/Sub OIDC verification is not configured")
    token = authorization.removeprefix("Bearer ") if authorization else ""
    if not token:
        raise HTTPException(status_code=401, detail="Missing Pub/Sub identity token")
    try:
        claims = id_token.verify_oauth2_token(token, GoogleAuthRequest(), audience=audience)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid Pub/Sub identity token") from exc
    if claims.get("email") != expected_email or claims.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="Unexpected Pub/Sub push identity")


def verify_service_token(authorization: str | None) -> None:
    """Validate the shared Modal-to-worker bearer token (constant-time compare)."""
    expected = os.getenv("CICERO_RAG_SERVICE_TOKEN", "")
    if not expected:
        raise HTTPException(status_code=503, detail="RAG service token is not configured")
    supplied = authorization.removeprefix("Bearer ") if authorization else ""
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


def create_worker_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    worker = RagWorker(settings)
    app = FastAPI(title="Cicero Cloud RAG Worker", version="1.0.0")

    @app.on_event("startup")
    async def startup() -> None:
        await worker.start()

    @app.on_event("shutdown")
    async def shutdown() -> None:
        await worker.close()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"service": "cicero-rag-worker", "status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        if not worker.database.is_started:
            raise HTTPException(status_code=503, detail="Cloud SQL is not ready")
        try:
            await worker.database.ping()
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Cloud SQL is unavailable") from exc
        return {"service": "cicero-rag-worker", "status": "ready"}

    @app.post("/pubsub/push")
    async def pubsub_push(
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_pubsub_identity(authorization, settings)
        envelope = await request.json()
        try:
            message = envelope["message"]
            payload = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
        except Exception:
            logger.exception("Malformed Pub/Sub envelope; dropping message")
            return {"ok": False, "dropped": True}
        # Legal PDFs can run to 500-600 pages: CPU ingestion far exceeds
        # Pub/Sub's 600s ack deadline and Cloud Run's request timeout, so the
        # message is acknowledged immediately and processing continues in the
        # background (requires Cloud Run CPU-always-allocated). A lease +
        # heartbeat guards against duplicate and crashed runs.
        task = asyncio.create_task(worker.process_message(payload))

        def _on_done(done_task: asyncio.Task) -> None:
            if done_task.cancelled():
                return
            exc = done_task.exception()
            if exc is None or isinstance(exc, ProcessingAlreadyRunning):
                return
            logger.error("Background document processing failed: %s", exc)
            asyncio.create_task(worker.mark_failed(payload, exc))

        task.add_done_callback(_on_done)
        return {"ok": True, "accepted": True}

    @app.post("/retrieve")
    async def retrieve(
        payload: dict[str, Any],
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        verify_service_token(authorization)
        try:
            return await worker.retrieve(payload)
        except Exception as exc:
            logger.exception("RAG retrieval failed")
            raise HTTPException(status_code=500, detail="RAG retrieval failed") from exc

    return app


app = create_worker_app()
