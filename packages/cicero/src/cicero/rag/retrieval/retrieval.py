"""Prototype-faithful retrieval orchestration for Cicero's pgvector store.

Ports the Argon prototype's QueryRouter, Reciprocal Rank Fusion, context
packing and strict EvidenceValidator onto Cicero's Cloud SQL schema. Pure
stdlib (plus the vendored ``cicero.rag.argon.schemas`` dataclasses): no ML or
database imports, so this module is unit-testable without Docling, pandas,
FlagEmbedding or a live PostgreSQL instance. The Cloud Run worker
(``cicero.rag_worker.service``) owns all SQL and model loading.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from cicero.rag.ingestion.schemas import EvidenceItem, QueryPlan, ValidationStatus

# Chunk types that may receive dense embeddings and enter hybrid retrieval
# (prototype: only indexable types; parent_section/table_summary do not).
INDEXABLE_CHUNK_TYPES: frozenset[str] = frozenset(
    {"clause", "table_raw", "table_row_group", "fallback_page"}
)

# Marker emitted by LegalTableProcessor.generate_retrieval_summary. Summaries
# are retrieval aids only and must never become authoritative evidence.
RETRIEVAL_AID_MARKER = "[RETRIEVAL AID SUMMARY ONLY"


def estimate_tokens(text: str) -> int:
    """Deterministic token estimate identical to the chunker's offline fallback."""
    if not text:
        return 0
    return max(1, len(re.findall(r"[A-Za-z]{1,6}|\d+|[^\w\s]", text)))


# ============================================================================
# QUERY CLASSIFIER & SCHEMA-VALIDATED ROUTER (prototype Component 10)
# ============================================================================


class QueryRouter:
    EXACT_CLAUSE_RE = re.compile(
        r"\b(?:retrieve|show|get|read|find|what\s+is\s+in)\s+(?:clause|section|article|schedule|annexure)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))+|[0-9]+(?:\.[0-9]+)*\b|[IVXLCDM]+\b|[A-Z]\b)",
        re.IGNORECASE,
    )
    DEFINED_TERM_RE = re.compile(
        r"(?:what\s+does\s+[\"']?([A-Z][A-Za-z0-9\s\-]{1,40}?)[\"']?\s+mean|define\s+[\"']?([A-Z][A-Za-z0-9\s\-]{1,40}?)[\"']?|definition\s+of\s+[\"']?([A-Z][A-Za-z0-9\s\-]{1,40}?)[\"']?)",
        re.IGNORECASE,
    )
    XREF_QUERY_RE = re.compile(
        r"(?:subject\s+to|notwithstanding|refer(?:s|\s+to)?|reference(?:s)?|governed\s+by)\s+(?:(section|clause|article|schedule|annexure)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))+|[0-9]+(?:\.[0-9]+)*\b|[IVXLCDM]+\b|[A-Z]\b))",
        re.IGNORECASE,
    )
    TEMPORAL_QUERY_RE = re.compile(
        r"\b(expire|expiration|effective\s+date|execution\s+date|amendment\s+date|notice\s+date|q[1-4]\s+\d{4}|in\s+202[4-9])\b",
        re.IGNORECASE,
    )
    MULTI_DOC_RE = re.compile(
        r"\b(compare|comparison|between\s+these\s+two|across\s+both\s+agreements|both\s+contracts|two\s+agreements)\b",
        re.IGNORECASE,
    )
    TABLE_QUERY_RE = re.compile(
        r"\b(how\s+many\s+shares|capitalization\s+table|ownership\s+percentage|invested\s+capital|milestone\s+payment|release\s+amount|vesting\s+tranche|vested\s+shares|monthly\s+fee)\b",
        re.IGNORECASE,
    )

    def route(
        self,
        query: str,
        case_id: str,
        org_id: str = "ORG_DEFAULT",
        target_document_ids: list[str] | None = None,
        target_document_type: str | None = None,
        target_chunk_types: list[str] | None = None,
        target_node_id: str | None = None,
        token_budget: int = 3000,
    ) -> QueryPlan:
        q_clean = query.strip()

        if self.MULTI_DOC_RE.search(q_clean):
            return QueryPlan(
                query=q_clean,
                query_type="multi_doc_comparison",
                case_id=case_id,
                org_id=org_id,
                target_document_ids=target_document_ids,
                target_document_type=target_document_type,
                target_chunk_types=target_chunk_types,
                target_node_id=target_node_id,
                token_budget=token_budget,
            )

        lowered = q_clean.lower()
        if any(
            w in lowered
            for w in [
                "what provisions",
                "which clauses",
                "which sections",
                "what is subject to",
                "notwithstanding",
            ]
        ):
            m_xref = self.XREF_QUERY_RE.search(q_clean)
            if m_xref:
                kind = m_xref.group(1).strip()
                ident = m_xref.group(2).strip()
                lbl = (
                    f"{kind} {ident}"
                    if kind.lower() in ("article", "schedule", "annexure")
                    else ident
                )
                x_type = (
                    "subject_to"
                    if "subject to" in lowered
                    else ("notwithstanding" if "notwithstanding" in lowered else None)
                )
                return QueryPlan(
                    query=q_clean,
                    query_type="cross_reference",
                    case_id=case_id,
                    org_id=org_id,
                    target_document_ids=target_document_ids,
                    target_document_type=target_document_type,
                    target_chunk_types=target_chunk_types,
                    target_node_id=target_node_id,
                    target_xref_label=lbl,
                    target_xref_type=x_type,
                    token_budget=token_budget,
                )

        m_exact = self.EXACT_CLAUSE_RE.search(q_clean)
        if m_exact and not any(w in lowered for w in ["subject to", "notwithstanding"]):
            raw_lbl = m_exact.group(1).strip()
            if "article" in lowered and not raw_lbl.lower().startswith("article"):
                raw_lbl = f"ARTICLE {raw_lbl}"
            elif "schedule" in lowered and not raw_lbl.lower().startswith("schedule"):
                raw_lbl = f"Schedule {raw_lbl}"
            elif "annexure" in lowered and not raw_lbl.lower().startswith("annexure"):
                raw_lbl = f"Annexure {raw_lbl}"
            return QueryPlan(
                query=q_clean,
                query_type="exact_clause",
                case_id=case_id,
                org_id=org_id,
                target_document_ids=target_document_ids,
                target_document_type=target_document_type,
                target_chunk_types=target_chunk_types,
                target_node_id=target_node_id,
                target_clause_label=raw_lbl,
                token_budget=token_budget,
            )

        m_def = self.DEFINED_TERM_RE.search(q_clean)
        if m_def:
            term = (m_def.group(1) or m_def.group(2) or m_def.group(3)).strip(" ?\"'")
            return QueryPlan(
                query=q_clean,
                query_type="defined_term",
                case_id=case_id,
                org_id=org_id,
                target_document_ids=target_document_ids,
                target_document_type=target_document_type,
                target_chunk_types=target_chunk_types,
                target_node_id=target_node_id,
                target_defined_term=term,
                token_budget=token_budget,
            )

        if self.TABLE_QUERY_RE.search(q_clean):
            return QueryPlan(
                query=q_clean,
                query_type="table_lookup",
                case_id=case_id,
                org_id=org_id,
                target_document_ids=target_document_ids,
                target_document_type=target_document_type,
                target_chunk_types=target_chunk_types,
                target_node_id=target_node_id,
                table_query_params=self._parse_table_params(q_clean),
                token_budget=token_budget,
            )

        if self.TEMPORAL_QUERY_RE.search(q_clean):
            role, start_iso, end_iso = self._parse_temporal_filters(q_clean)
            return QueryPlan(
                query=q_clean,
                query_type="metadata_temporal",
                case_id=case_id,
                org_id=org_id,
                target_document_ids=target_document_ids,
                target_document_type=target_document_type,
                target_chunk_types=target_chunk_types,
                target_node_id=target_node_id,
                date_role_filter=role,
                date_start_iso=start_iso,
                date_end_iso=end_iso,
                token_budget=token_budget,
            )

        return QueryPlan(
            query=q_clean,
            query_type="semantic",
            case_id=case_id,
            org_id=org_id,
            target_document_ids=target_document_ids,
            target_document_type=target_document_type,
            target_chunk_types=target_chunk_types,
            target_node_id=target_node_id,
            token_budget=token_budget,
        )

    @staticmethod
    def _parse_table_params(q: str) -> dict[str, Any]:
        ql = q.lower()
        params: dict[str, Any] = {
            "caption_hint": None,
            "row_filter_col": None,
            "row_filter_val": None,
            "aggregation": None,
            "agg_column": None,
        }
        if "milestone" in ql or "release amount" in ql or "escrow" in ql:
            params["caption_hint"] = "Milestone"
            if "total" in ql or "sum" in ql:
                params["aggregation"] = "sum"
                params["agg_column"] = "Release Amount (USD)"
            for ms in ["ms-01", "ms-02", "ms-03", "ms-04"]:
                if ms in ql:
                    params["row_filter_col"] = "Milestone ID"
                    params["row_filter_val"] = ms.upper()
        elif "vesting" in ql or "tranche" in ql:
            params["caption_hint"] = "Vesting"
            if "founder a" in ql:
                params["row_filter_col"] = "Beneficiary"
                params["row_filter_val"] = "Founder A"
            elif "founder b" in ql:
                params["row_filter_col"] = "Beneficiary"
                params["row_filter_val"] = "Founder B"
            if "total" in ql or "sum" in ql:
                params["aggregation"] = "sum"
                params["agg_column"] = "Vested Shares"
        else:
            params["caption_hint"] = "Capitalization"
            for entity in [
                "Founder A",
                "Founder B",
                "Investor C",
                "Horizon Ventures LP",
                "Employee Option Pool",
            ]:
                if entity.lower() in ql:
                    params["row_filter_col"] = "Shareholder"
                    params["row_filter_val"] = entity
                    break
            if "total" in ql or "sum" in ql:
                params["aggregation"] = "sum"
                params["agg_column"] = (
                    "Invested Capital (USD)"
                    if "capital" in ql or "invested" in ql
                    else "Shares"
                )
        return params

    @staticmethod
    def _parse_temporal_filters(q: str) -> tuple[str | None, str | None, str | None]:
        ql = q.lower()
        role: str | None = None
        if "notice" in ql or "cure" in ql:
            role = "notice"
        elif "amendment" in ql:
            role = "amendment"
        elif "expire" in ql or "expiration" in ql:
            role = "expiration"
        elif "effective" in ql:
            role = "effective"
        elif "execution" in ql:
            role = "execution"

        m_q = re.search(r"\bq([1-4])\s+(\d{4})\b", ql)
        if m_q:
            q_bounds = {
                1: ("{}-01-01", "{}-03-31"),
                2: ("{}-04-01", "{}-06-30"),
                3: ("{}-07-01", "{}-09-30"),
                4: ("{}-10-01", "{}-12-31"),
            }
            start_fmt, end_fmt = q_bounds[int(m_q.group(1))]
            year = m_q.group(2)
            return role, start_fmt.format(year), end_fmt.format(year)

        return role, None, None


# ============================================================================
# RECIPROCAL RANK FUSION (prototype Component 11)
# ============================================================================


def reciprocal_rank_fusion(
    dense_list: list[dict[str, Any]],
    lexical_list: list[dict[str, Any]],
    k: int = 60,
) -> list[dict[str, Any]]:
    """Merge dense + lexical ranked lists with RRF (k=60), de-duplicating by chunk."""
    by_chunk_id: dict[str, dict[str, Any]] = {}

    for rank_idx, item in enumerate(dense_list):
        cid = item["chunk_id"]
        rank = rank_idx + 1
        by_chunk_id[cid] = {
            "chunk_id": cid,
            "payload": item["payload"],
            "dense_score": item["score"],
            "lexical_score": 0.0,
            "sparse_score": 0.0,
            "dense_rank": rank,
            "lexical_rank": None,
            "sparse_rank": None,
            "rrf_score": 1.0 / (k + rank),
        }

    for rank_idx, item in enumerate(lexical_list):
        cid = item["chunk_id"]
        rank = rank_idx + 1
        contrib = 1.0 / (k + rank)
        if cid in by_chunk_id:
            by_chunk_id[cid]["lexical_score"] = item["score"]
            by_chunk_id[cid]["sparse_score"] = item["score"]
            by_chunk_id[cid]["lexical_rank"] = rank
            by_chunk_id[cid]["sparse_rank"] = rank
            by_chunk_id[cid]["rrf_score"] += contrib
        else:
            by_chunk_id[cid] = {
                "chunk_id": cid,
                "payload": item["payload"],
                "dense_score": 0.0,
                "lexical_score": item["score"],
                "sparse_score": item["score"],
                "dense_rank": None,
                "lexical_rank": rank,
                "sparse_rank": rank,
                "rrf_score": contrib,
            }

    fused_list = list(by_chunk_id.values())
    for f in fused_list:
        f["rrf_score"] = round(f["rrf_score"], 6)
        f["score"] = f["rrf_score"]

    fused_list.sort(key=lambda x: (x["rrf_score"], x["dense_score"]), reverse=True)
    return fused_list


# ============================================================================
# CONTEXT PACKING (prototype Component 16)
# ============================================================================


def pack_context(
    matched_chunks: list[EvidenceItem],
    definitions: list[EvidenceItem],
    parents: list[EvidenceItem],
    cross_refs: list[EvidenceItem],
    raw_tables: list[EvidenceItem],
    token_budget: int = 3000,
    count_tokens: Callable[[str], int] | None = None,
) -> tuple[list[EvidenceItem], dict[str, Any]]:
    """Pack evidence into the token budget in prototype priority order."""
    counter = count_tokens or estimate_tokens
    priority_buckets = [matched_chunks, definitions, parents, cross_refs, raw_tables]

    packed: list[EvidenceItem] = []
    seen_keys: set[tuple[str, str, int, int]] = set()
    used_tokens = 0
    dropped_for_budget = 0

    for bucket in priority_buckets:
        for item in bucket:
            dedup_key = (item.document_id, item.node_id, item.char_start, item.char_end)
            if dedup_key in seen_keys:
                continue
            if item.token_count <= 0:
                item.token_count = counter(item.original_source_text)
            if used_tokens + item.token_count > token_budget:
                dropped_for_budget += 1
                continue
            seen_keys.add(dedup_key)
            used_tokens += item.token_count
            item.evidence_id = f"EV_{len(packed) + 1:03d}"
            packed.append(item)

    pack_stats = {
        "token_budget": token_budget,
        "tokens_used": used_tokens,
        "items_packed": len(packed),
        "items_dropped_for_budget": dropped_for_budget,
    }
    return packed, pack_stats


# ============================================================================
# STRICT DETERMINISTIC EVIDENCE VALIDATOR (prototype Component 17)
# ============================================================================


@dataclass
class ParsedDocView:
    """DB-backed stand-in for the prototype's ParsedDocument during validation."""

    document_id: str
    full_text: str
    pages: dict[int, tuple[int, int]] = field(default_factory=dict)
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)


class EvidenceValidator:
    """Validates evidence against per-document views resolved from the DB.

    ``resolve_view`` is called with a document_id (as stored on evidence items)
    and returns a :class:`ParsedDocView` or ``None`` when the document is not
    part of the requested case (views are built case-scoped by the caller, so
    ``None`` means the item references an unknown or cross-case document).
    """

    def __init__(self, resolve_view: Callable[[str], ParsedDocView | None]) -> None:
        self._resolve_view = resolve_view
        self._view_cache: dict[str, ParsedDocView | None] = {}

    def _view(self, document_id: str) -> ParsedDocView | None:
        if document_id not in self._view_cache:
            self._view_cache[document_id] = self._resolve_view(document_id)
        return self._view_cache[document_id]

    def validate_single_item(
        self,
        item: EvidenceItem,
        requested_case_id: str,
        requested_org_id: str = "ORG_DEFAULT",
        doc_view: ParsedDocView | None = None,
    ) -> tuple[str, str]:
        if (
            not item.document_id
            or not item.case_id
            or not item.node_id
            or not item.why_included
            or not item.original_source_text
            or item.page is None
            or item.page < 1
            or item.char_start is None
            or item.char_end is None
            or item.char_start < 0
            or item.char_end <= item.char_start
        ):
            return (
                ValidationStatus.INSUFFICIENT_PROVENANCE,
                "Missing required provenance fields or invalid offset bounds.",
            )

        if (
            item.generated_summaries is not None
            or RETRIEVAL_AID_MARKER in item.original_source_text
        ):
            return (
                ValidationStatus.INSUFFICIENT_PROVENANCE,
                "Generated table/text summaries cannot be used as authoritative evidence.",
            )

        if item.org_id != requested_org_id:
            return (
                ValidationStatus.INVALID_SOURCE_REFERENCE,
                f"Org ID mismatch: item has '{item.org_id}', expected '{requested_org_id}'.",
            )

        if item.case_id != requested_case_id:
            return (
                ValidationStatus.INVALID_SOURCE_REFERENCE,
                f"Case ID mismatch: item has '{item.case_id}', expected '{requested_case_id}'.",
            )

        if doc_view is None:
            doc_view = self._view(item.document_id)
        if doc_view is None:
            return (
                ValidationStatus.INVALID_SOURCE_REFERENCE,
                f"Referenced document_id '{item.document_id}' does not exist.",
            )

        if item.page not in doc_view.pages:
            return (
                ValidationStatus.INVALID_SOURCE_REFERENCE,
                f"Referenced page {item.page} does not exist in document '{item.document_id}'.",
            )

        if item.char_end > len(doc_view.full_text):
            return (
                ValidationStatus.INVALID_SOURCE_REFERENCE,
                f"char_end ({item.char_end}) exceeds document length ({len(doc_view.full_text)}).",
            )

        is_table_item = (
            item.why_included == "raw_table"
            or item.table_id is not None
            or item.node_id.startswith("N_TBL_")
        )
        if is_table_item:
            raw_tbl = doc_view.tables.get(item.table_id or "")
            if raw_tbl is None:
                return (
                    ValidationStatus.INVALID_TABLE_REFERENCE,
                    f"Referenced table_id '{item.table_id}' does not exist "
                    f"in '{item.document_id}'.",
                )
            if item.page != raw_tbl.get("page"):
                return (
                    ValidationStatus.INVALID_TABLE_REFERENCE,
                    f"Table '{item.table_id}' is on page {raw_tbl.get('page')}, "
                    f"not page {item.page}.",
                )
            valid_cells = {
                (c.get("row_index"), c.get("col_index")): c
                for c in raw_tbl.get("cells", [])
            }
            for cell_ref in item.table_cell_references:
                key = (cell_ref.get("row_index"), cell_ref.get("col_index"))
                if key not in valid_cells:
                    return (
                        ValidationStatus.INVALID_TABLE_REFERENCE,
                        f"Invalid table cell coordinate {key} in table '{item.table_id}'.",
                    )
                canonical_cell = valid_cells[key]
                if str(cell_ref.get("raw_cell_value")) != str(
                    canonical_cell.get("raw_cell_value")
                ):
                    return (
                        ValidationStatus.INVALID_TABLE_REFERENCE,
                        f"Cell {key} value mismatch in table '{item.table_id}'.",
                    )
                c_slice = doc_view.full_text[
                    canonical_cell["char_start"] : canonical_cell["char_end"]
                ]
                if c_slice != canonical_cell.get("raw_cell_value"):
                    return (
                        ValidationStatus.INVALID_TABLE_REFERENCE,
                        f"Cell {key} character span mismatch in full_text.",
                    )
        else:
            hier_node = doc_view.nodes.get(item.node_id)
            if hier_node is None or hier_node.get("document_id") != item.document_id:
                return (
                    ValidationStatus.INVALID_SOURCE_REFERENCE,
                    f"Referenced hierarchy node '{item.node_id}' does not exist "
                    f"in '{item.document_id}'.",
                )
            page_start = hier_node.get("page_start")
            page_end = hier_node.get("page_end")
            if page_start is None or page_end is None or not (
                page_start <= item.page <= page_end
            ):
                return (
                    ValidationStatus.INVALID_SOURCE_REFERENCE,
                    f"Page {item.page} is outside node '{item.node_id}' page bounds "
                    f"({page_start}..{page_end}).",
                )

        canonical_span_slice = doc_view.full_text[item.char_start : item.char_end]
        if item.original_source_text != canonical_span_slice:
            return (
                ValidationStatus.SPAN_MISMATCH,
                f"Strict span mismatch at {item.document_id}[{item.char_start}:{item.char_end}]: "
                "original_source_text does not match canonical document slice.",
            )

        page_char_start, page_char_end = doc_view.pages[item.page]
        if item.char_start < page_char_start or item.char_start > page_char_end:
            return (
                ValidationStatus.SPAN_MISMATCH,
                f"Span start {item.char_start} does not fall on page {item.page} "
                f"(page char bounds {page_char_start}:{page_char_end}).",
            )

        return ValidationStatus.VERIFIED, "Strict source span and provenance verified."

    def validate_evidence_list(
        self,
        items: list[EvidenceItem],
        requested_case_id: str,
        requested_org_id: str = "ORG_DEFAULT",
        token_budget: int = 3000,
    ) -> tuple[list[EvidenceItem], list[dict[str, Any]]]:
        verified_items: list[EvidenceItem] = []
        rejection_log: list[dict[str, Any]] = []
        running_tokens = 0

        for item in items:
            doc_view = self._view(item.document_id) if item.document_id else None
            status, reason = self.validate_single_item(
                item,
                requested_case_id=requested_case_id,
                requested_org_id=requested_org_id,
                doc_view=doc_view,
            )
            if status != ValidationStatus.VERIFIED:
                item.validation_status = status
                item.validation_diagnostics = reason
                rejection_log.append(
                    {
                        "evidence_id": item.evidence_id,
                        "node_id": item.node_id,
                        "status": status,
                        "reason": reason,
                    }
                )
                continue

            if running_tokens + item.token_count > token_budget:
                item.validation_status = ValidationStatus.INSUFFICIENT_PROVENANCE
                item.validation_diagnostics = "Token budget exceeded during validation."
                rejection_log.append(
                    {
                        "evidence_id": item.evidence_id,
                        "node_id": item.node_id,
                        "status": "TOKEN_BUDGET_EXCEEDED",
                        "reason": "Token budget exceeded.",
                    }
                )
                continue

            running_tokens += item.token_count
            item.validation_status = ValidationStatus.VERIFIED
            item.validation_diagnostics = reason
            verified_items.append(item)

        for idx, it in enumerate(verified_items):
            it.evidence_id = f"EV_{idx + 1:03d}"
        return verified_items, rejection_log
