from __future__ import annotations

import hashlib
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from cicero.rag.argon.chunker import HierarchicalLegalChunker
from cicero.rag.argon.docling_parser import DoclingLegalParser
from cicero.rag.argon.schemas import LocalFilesystemDocumentStorage
from cicero.rag.argon.structural_processor import (
    CrossReferenceExtractor,
    DefinitionsExtractor,
    LegalDateExtractor,
    LegalHierarchyParser,
)


class LegalRagPipeline:
    """Runs Argon's parser, legal structure extraction and hierarchical chunking."""

    def __init__(self, *, enable_ocr: bool = True, use_docling: bool = True) -> None:
        self._temp_root = tempfile.mkdtemp(prefix="cicero-rag-")
        self.storage = LocalFilesystemDocumentStorage(self._temp_root)
        self.parser = DoclingLegalParser(
            doc_storage=self.storage,
            enable_ocr=enable_ocr,
            ocr_engine_name="docling_default_ocr",
            use_docling=use_docling,
        )
        self.hierarchy = LegalHierarchyParser()
        self.definitions = DefinitionsExtractor()
        self.cross_references = CrossReferenceExtractor()
        self.dates = LegalDateExtractor()
        self.chunker = HierarchicalLegalChunker(
            child_target_tokens=250,
            parent_max_tokens=2000,
            model_max_input_tokens=8192,
        )

    def process_document(
        self,
        file_path: str,
        *,
        document_id: str,
        case_id: str,
        organization_id: str,
        document_type: str = "pdf",
    ) -> dict[str, Any]:
        parsed = self.parser.parse_document(
            filepath=file_path,
            document_id=document_id,
            case_id=case_id,
            document_type=document_type,
            org_id=organization_id,
        )
        if parsed.ingestion_status == "FAILED":
            warnings = "; ".join(parsed.parsing_warnings)
            raise RuntimeError(
                "Docling could not extract usable document content: " + warnings
            )
        nodes, structure_confidence, hierarchy_warnings = self.hierarchy.parse_hierarchy(parsed)
        definitions = self.definitions.extract_definitions(parsed, nodes)
        cross_references = self.cross_references.extract_cross_references(parsed, nodes)
        dates = self.dates.extract_dates(parsed, nodes)
        chunks = self.chunker.build_chunks(parsed, nodes, dates, include_table_summaries=True)
        if not parsed.full_text.strip() or not chunks:
            raise RuntimeError("Document parsing produced no indexable text chunks.")
        for item in definitions:
            item.org_id = organization_id
        for item in cross_references:
            item.org_id = organization_id
        return {
            "parsed": parsed,
            "nodes": nodes,
            "definitions": definitions,
            "cross_references": cross_references,
            "dates": dates,
            "chunks": chunks,
            "structure_confidence": structure_confidence,
            "warnings": list(parsed.parsing_warnings) + list(hierarchy_warnings),
            "file_sha256": hashlib.sha256(Path(file_path).read_bytes()).hexdigest(),
            "tokenizer": self.chunker.tokenizer_name,
        }


def json_safe(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return json_safe(value.to_dict())
    if hasattr(value, "__dataclass_fields__"):
        return json_safe(asdict(value))
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if hasattr(value, "item"):
        try:
            return value.item()
        except (ValueError, TypeError):
            pass
    return value
