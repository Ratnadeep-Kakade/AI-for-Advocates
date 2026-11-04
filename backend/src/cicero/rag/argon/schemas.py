"""
Module 1: Canonical Data Schemas & Storage Adapter Boundaries (PostgreSQL + pgvector Edition)
Updated for PostgreSQL + pgvector Architecture:
1. Adds multi-tenant `org_id` isolation alongside `case_id` across all schemas and queries.
2. Preserves external object storage references (`storage_uri`) on `ParsedDocument` so raw PDF/DOCX
   binaries are never stored inside PostgreSQL.
3. Adds `document_type` and `legal_identifiers` (`List[str]`) to `LegalChunk` so PostgreSQL
   Full-Text Search (`tsvector`) is paired with exact legal identifier array indexing (`4.2(b)(ii)`,
   `Section 7.1`, `Schedule II`).
4. Retains strict separation of `original_source_text`, `extracted_text`, `derived_annotations`,
   and `generated_summaries` on `EvidenceItem`.
"""

import os
import re
import json
import sqlite3
import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Tuple


class ValidationStatus:
    VERIFIED = "VERIFIED"
    INVALID_SOURCE_REFERENCE = "INVALID_SOURCE_REFERENCE"
    SPAN_MISMATCH = "SPAN_MISMATCH"
    QUOTE_NOT_FOUND = "QUOTE_NOT_FOUND"
    INVALID_TABLE_REFERENCE = "INVALID_TABLE_REFERENCE"
    INSUFFICIENT_PROVENANCE = "INSUFFICIENT_PROVENANCE"
    PENDING = "PENDING"


# ============================================================================
# LEGAL IDENTIFIER EXTRACTION HELPER (PRESERVES 4.2(b)(ii), Section 7.1, Schedule II)
# ============================================================================

ROMAN_TO_ARABIC_ID = {
    "i": "1", "ii": "2", "iii": "3", "iv": "4", "v": "5",
    "vi": "6", "vii": "7", "viii": "8", "ix": "9", "x": "10",
}
ARABIC_TO_ROMAN_ID = {v: k for k, v in ROMAN_TO_ARABIC_ID.items()}

CLAUSE_ID_RE = re.compile(
    r"(?:(?<=^)|(?<=[\s\(\[,;]))([0-9]+(?:\.[0-9]+)+(?:\([a-zA-Z0-9]+\))*|[0-9]+\([a-zA-Z0-9]+\)(?:\([a-zA-Z0-9]+\))*)"
)
NAMED_REF_ID_RE = re.compile(
    r"\b(article|section|clause|sub-clause|schedule|annexure)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*|[ivxlcdm]+|[a-z])\b",
    re.IGNORECASE,
)


def extract_legal_identifiers(text: str, clause_label: str = "") -> List[str]:
    """
    Extracts canonical legal identifiers from text and clause_label so that
    PostgreSQL tokenization never destroys identifiers like `4.2(b)(ii)`,
    `Section 7.1`, `Article IV`, or `Schedule II`.
    Also generates Roman <-> Arabic aliases for Articles and Schedules.
    """
    ids: List[str] = []
    seen = set()

    def _add(val: str) -> None:
        v = val.strip().lower()
        if v and v not in seen:
            seen.add(v)
            ids.append(v)

    if clause_label:
        lbl = clause_label.strip()
        _add(lbl)
        # Also add prefixes if it's a bare number/clause label
        if re.match(r"^\d", lbl):
            _add(f"section {lbl}")
            _add(f"clause {lbl}")
            # Add parent prefixes, e.g. for 4.2(b)(ii) -> also index 4.2(b) and 4.2
            base_m = re.match(r"^(\d+\.\d+)(?:\(([a-zA-Z0-9]+)\))?(?:\(([a-zA-Z0-9]+)\))?", lbl)
            if base_m:
                _add(base_m.group(1))
                if base_m.group(2):
                    _add(f"{base_m.group(1)}({base_m.group(2)})")
        elif lbl.lower().startswith(("article ", "schedule ", "annexure ")):
            parts = lbl.split()
            if len(parts) == 2:
                kind, num = parts[0].lower(), parts[1].lower()
                _add(f"{kind} {num}")
                if num in ROMAN_TO_ARABIC_ID:
                    _add(f"{kind} {ROMAN_TO_ARABIC_ID[num]}")
                elif num in ARABIC_TO_ROMAN_ID:
                    _add(f"{kind} {ARABIC_TO_ROMAN_ID[num]}")

    combined = f"{clause_label} {text}" if clause_label else text
    for m in CLAUSE_ID_RE.finditer(combined):
        tok = m.group(1)
        _add(tok)
        _add(f"section {tok}")
        _add(f"clause {tok}")

    for m in NAMED_REF_ID_RE.finditer(combined):
        kind = m.group(1).lower()
        ident = m.group(2).lower()
        if kind == "sub-clause":
            kind = "clause"
        _add(f"{kind} {ident}")
        _add(ident)
        if kind in ("article", "schedule"):
            if ident in ROMAN_TO_ARABIC_ID:
                _add(f"{kind} {ROMAN_TO_ARABIC_ID[ident]}")
            elif ident in ARABIC_TO_ROMAN_ID:
                _add(f"{kind} {ARABIC_TO_ROMAN_ID[ident]}")

    return ids


# ============================================================================
# CANONICAL DOCUMENT & STRUCTURAL SCHEMAS
# ============================================================================

@dataclass
class BoundingBox:
    page: int
    l: float
    t: float
    r: float
    b: float
    coord_origin: str = "BOTTOMLEFT"

    def to_list(self) -> List[float]:
        return [round(self.l, 2), round(self.t, 2), round(self.r, 2), round(self.b, 2)]


@dataclass
class PageInfo:
    page_number: int
    width: Optional[float]
    height: Optional[float]
    char_start: int
    char_end: int
    ocr_executed: bool = False
    ocr_engine: Optional[str] = None
    ocr_confidence: Optional[float] = None
    extraction_quality: str = "VERIFIED_DIGITAL"
    simulated_uncertainty_for_test: bool = False


@dataclass
class TextBlock:
    block_id: str
    page: int
    text: str
    bbox: Optional[List[float]]
    char_start: int
    char_end: int
    docling_label: str = "text"
    ocr_confidence: Optional[float] = None


@dataclass
class LogicalTextUnit:
    unit_id: str
    document_id: str
    source_block_ids: List[str]
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    bbox: Optional[List[float]]
    text: str
    reconstructed_from_multiple_blocks: bool = False


@dataclass
class TableCellProvenance:
    table_id: str
    row_index: int
    col_index: int
    row_identifier: str
    col_header: str
    raw_cell_value: str
    page: int
    char_start: int
    char_end: int

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RawTable:
    table_id: str
    document_id: str
    caption: str
    headers: List[str]
    rows: List[List[str]]
    page: int
    parent_node_id: Optional[str] = None
    bbox: Optional[List[float]] = None
    char_start: int = 0
    char_end: int = 0
    cells: List[TableCellProvenance] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ParsedDocument:
    document_id: str
    case_id: str
    filename: str
    document_type: str
    file_hash: str
    full_text: str
    pages: List[PageInfo]
    text_blocks: List[TextBlock]
    tables: List[RawTable]
    metadata: Dict[str, Any]
    org_id: str = "ORG_DEFAULT"
    storage_uri: str = ""  # External object storage URI (never stores binary blobs in DB)
    parser_version: str = "docling-2.x-canonical-v3-pgvector"
    ingestion_status: str = "INGESTED"
    parsing_warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class HierarchyNode:
    node_id: str
    level: str
    depth: int
    label: str
    raw_number: str
    title: str
    text: str
    lead_in_text: str
    parent_id: Optional[str]
    children_ids: List[str]
    document_id: str
    page_start: int
    page_end: int
    char_start: int
    char_end: int
    bbox: Optional[List[float]] = None
    structure_confidence: str = "high"
    is_orphan: bool = False
    source_block_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DefinitionEntry:
    term: str
    definition: str
    extracted_meaning: str
    pattern_type: str
    document_id: str
    case_id: str
    node_id: str
    page: int
    char_start: int
    char_end: int
    org_id: str = "ORG_DEFAULT"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CrossReferenceEdge:
    edge_id: str
    document_id: str
    case_id: str
    from_node: str
    to_node: Optional[str]
    target_label: str
    normalized_reference: str
    type: str
    raw_text: str
    resolution_status: str
    resolved: bool
    is_external: bool = False
    external_citation: Optional[str] = None
    candidate_target_nodes: List[str] = field(default_factory=list)
    source_provenance: Dict[str, Any] = field(default_factory=dict)
    org_id: str = "ORG_DEFAULT"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DateRecord:
    date_id: str
    document_id: str
    case_id: str
    iso: Optional[str]
    raw: str
    role: str
    node_id: str
    page: int
    char_start: int
    char_end: int
    ambiguous: bool = False
    derived: bool = False
    derivation_rule: Optional[str] = None
    role_confidence: str = "high"
    org_id: str = "ORG_DEFAULT"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class LegalChunk:
    chunk_id: str
    case_id: str
    document_id: str
    chunk_type: str
    node_id: str
    parent_id: Optional[str]
    clause_label: str
    section_path: List[str]
    page: int
    bbox: Optional[List[float]]
    char_start: int
    char_end: int
    structure_confidence: str
    clean_text: str
    embedding_text: str
    token_count: int
    tokenizer_name: str = "whitespace-approx"
    table_id: Optional[str] = None
    retrieval_aid_only: bool = False
    effective_date: Optional[str] = None
    expiration_date: Optional[str] = None
    org_id: str = "ORG_DEFAULT"
    document_type: str = ""
    legal_identifiers: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.legal_identifiers:
            self.legal_identifiers = extract_legal_identifiers(self.clean_text, self.clause_label)

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


# ============================================================================
# QUERY ROUTING, DIAGNOSTICS & EVIDENCE PACK SCHEMAS
# ============================================================================

@dataclass
class QueryPlan:
    query: str
    query_type: str
    case_id: str
    org_id: str = "ORG_DEFAULT"
    target_document_ids: Optional[List[str]] = None
    target_document_type: Optional[str] = None
    target_chunk_types: Optional[List[str]] = None
    target_node_id: Optional[str] = None
    target_clause_label: Optional[str] = None
    target_defined_term: Optional[str] = None
    target_xref_label: Optional[str] = None
    target_xref_type: Optional[str] = None
    date_role_filter: Optional[str] = None
    date_start_iso: Optional[str] = None
    date_end_iso: Optional[str] = None
    table_query_params: Optional[Dict[str, Any]] = None
    top_k_dense: int = 50
    top_k_lexical: int = 50
    top_k_rerank: int = 8
    token_budget: int = 3000

    @property
    def top_k_sparse(self) -> int:
        return self.top_k_lexical

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceItem:
    evidence_id: str
    document_id: str
    case_id: str
    node_id: str
    page: int
    char_start: int
    char_end: int
    original_source_text: str
    extracted_text: str
    why_included: str
    validation_status: str = ValidationStatus.PENDING
    validation_diagnostics: str = ""
    derived_annotations: Dict[str, Any] = field(default_factory=dict)
    generated_summaries: Optional[str] = None
    table_cell_references: List[Dict[str, Any]] = field(default_factory=list)
    clause_label: str = ""
    score: float = 0.0
    token_count: int = 0
    table_id: Optional[str] = None
    external_statutory_hints: List[str] = field(default_factory=list)
    org_id: str = "ORG_DEFAULT"
    chunk_id: Optional[str] = None

    @property
    def content(self) -> str:
        return self.original_source_text

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["content"] = self.original_source_text
        return d


@dataclass
class ModelRuntimeMetadata:
    embedding_model_used: str
    reranker_model_used: str
    tokenizer_used: str
    database_backend: str
    lexical_search_backend: str
    simulation_mode_enabled: bool
    model_init_status: str

    @property
    def vector_store_backend(self) -> str:
        return self.database_backend

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QueryDiagnostics:
    query_classification: str
    retrieval_route_selected: str
    dense_candidates: List[Dict[str, Any]] = field(default_factory=list)
    lexical_candidates: List[Dict[str, Any]] = field(default_factory=list)
    exact_identifier_matches: List[Dict[str, Any]] = field(default_factory=list)
    rrf_results: List[Dict[str, Any]] = field(default_factory=list)
    reranker_scores: List[Dict[str, Any]] = field(default_factory=list)
    final_selected_chunks: List[str] = field(default_factory=list)
    parent_expansion_nodes: List[str] = field(default_factory=list)
    definition_injection_terms: List[str] = field(default_factory=list)
    cross_reference_resolutions: List[Dict[str, Any]] = field(default_factory=list)
    final_context_composition: Dict[str, Any] = field(default_factory=dict)
    rejected_evidence_items: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def sparse_candidates(self) -> List[Dict[str, Any]]:
        return self.lexical_candidates

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class EvidencePack:
    execution_id: str
    case_id: str
    query: str
    query_type: str
    evidence: List[EvidenceItem]
    retrieval_metadata: Dict[str, Any]
    insufficient_evidence: bool
    org_id: str = "ORG_DEFAULT"
    model_runtime: Optional[ModelRuntimeMetadata] = None
    diagnostics: Optional[QueryDiagnostics] = None
    message: str = "Evidence successfully retrieved and verified."
    external_research_hints: List[str] = field(default_factory=list)
    unresolved_terms: List[str] = field(default_factory=list)
    unresolved_references: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "org_id": self.org_id,
            "case_id": self.case_id,
            "query": self.query,
            "query_type": self.query_type,
            "evidence": [e.to_dict() for e in self.evidence],
            "retrieval_metadata": self.retrieval_metadata,
            "insufficient_evidence": self.insufficient_evidence,
            "model_runtime": self.model_runtime.to_dict() if self.model_runtime else None,
            "diagnostics": self.diagnostics.to_dict() if self.diagnostics else None,
            "message": self.message,
            "external_research_hints": self.external_research_hints,
            "unresolved_terms": self.unresolved_terms,
            "unresolved_references": self.unresolved_references,
        }


# ============================================================================
# EXTERNAL OBJECT STORAGE ADAPTER (STORES ORIGINAL PDF/DOCX BINARIES OUTSIDE DB)
# ============================================================================

class DocumentStorageAdapter(ABC):
    @abstractmethod
    def save_original_document(self, case_id: str, document_id: str, filename: str, file_bytes: bytes, org_id: str = "ORG_DEFAULT") -> Tuple[str, str]:
        pass

    @abstractmethod
    def save_parsed_document(self, parsed_doc: ParsedDocument) -> str:
        pass

    @abstractmethod
    def load_parsed_document(self, document_id: str) -> Optional[ParsedDocument]:
        pass


class LocalFilesystemDocumentStorage(DocumentStorageAdapter):
    """
    External Object Storage Adapter (Local Filesystem implementation for Colab;
    maps to S3/GCS URI `s3://bucket/org_id/case_id/...` in production).
    Original PDF/DOCX binaries are stored here and referenced via `storage_uri` in PostgreSQL.
    """

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.orig_dir = os.path.join(base_dir, "original_documents")
        self.parsed_dir = os.path.join(base_dir, "parsed_documents")
        os.makedirs(self.orig_dir, exist_ok=True)
        os.makedirs(self.parsed_dir, exist_ok=True)

    @staticmethod
    def compute_sha256(file_bytes: bytes) -> str:
        return hashlib.sha256(file_bytes).hexdigest()

    def save_original_document(
        self, case_id: str, document_id: str, filename: str, file_bytes: bytes, org_id: str = "ORG_DEFAULT"
    ) -> Tuple[str, str]:
        file_hash = self.compute_sha256(file_bytes)
        safe_name = f"{org_id}_{case_id}_{document_id}_{os.path.basename(filename)}"
        dest_path = os.path.join(self.orig_dir, safe_name)
        with open(dest_path, "wb") as f:
            f.write(file_bytes)
        storage_uri = f"file://{os.path.abspath(dest_path)}"
        return storage_uri, file_hash

    def save_parsed_document(self, parsed_doc: ParsedDocument) -> str:
        dest_path = os.path.join(self.parsed_dir, f"{parsed_doc.document_id}.json")
        with open(dest_path, "w", encoding="utf-8") as f:
            json.dump(parsed_doc.to_dict(), f, indent=2)
        return dest_path

    def load_parsed_document(self, document_id: str) -> Optional[ParsedDocument]:
        path = os.path.join(self.parsed_dir, f"{document_id}.json")
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        pages = [PageInfo(**p) for p in data["pages"]]
        blocks = [TextBlock(**b) for b in data["text_blocks"]]
        tables = []
        for t in data["tables"]:
            cells_data = t.pop("cells", [])
            cells = [TableCellProvenance(**c) for c in cells_data]
            tables.append(RawTable(**t, cells=cells))
        return ParsedDocument(
            document_id=data["document_id"],
            org_id=data.get("org_id", "ORG_DEFAULT"),
            case_id=data["case_id"],
            filename=data["filename"],
            document_type=data["document_type"],
            file_hash=data["file_hash"],
            storage_uri=data.get("storage_uri", ""),
            full_text=data["full_text"],
            pages=pages,
            text_blocks=blocks,
            tables=tables,
            metadata=data["metadata"],
            parser_version=data.get("parser_version", "docling-2.x-canonical-v3-pgvector"),
            ingestion_status=data.get("ingestion_status", "INGESTED"),
            parsing_warnings=data.get("parsing_warnings", []),
        )


class StructuredStorageAdapter(ABC):
    @abstractmethod
    def check_duplicate_hash(self, case_id: str, file_hash: str, org_id: str = "ORG_DEFAULT") -> Optional[str]:
        pass

    @abstractmethod
    def register_document(self, parsed_doc: ParsedDocument, structure_confidence: str) -> None:
        pass

    @abstractmethod
    def delete_document_records(self, document_id: str) -> Dict[str, int]:
        pass
