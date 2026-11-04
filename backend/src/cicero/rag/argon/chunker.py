"""
Module 5: Component 7 — Token-Aware Hierarchical Parent-Child & Table Chunker
Updated per Technical Audit (Section 2B & Section 7):
1. Uses the actual HuggingFace tokenizer (`AutoTokenizer.from_pretrained('BAAI/bge-m3')`) when
   available to compute exact subword token counts and enforce model input limits (`max_model_tokens=8192`),
   falling back to a deterministic regex subword tokenizer only when running offline without HuggingFace weights,
   and explicitly recording `tokenizer_name` on every `LegalChunk`.
2. Preserves exact verbatim `clean_text = parsed_doc.full_text[char_start:char_end]` on every chunk
   so that every child chunk, parent chunk, and raw table chunk passes strict source-span identity validation.
"""

import re
from typing import List, Dict, Optional
from .schemas import ParsedDocument, HierarchyNode, RawTable, LegalChunk, DateRecord
from .structural_processor import LegalTableProcessor

try:
    from transformers import AutoTokenizer
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False


class HierarchicalLegalChunker:
    """Component 7: Token-aware parent-child legal chunker with strict offset provenance."""

    def __init__(
        self,
        child_target_tokens: int = 250,
        parent_max_tokens: int = 2000,
        model_max_input_tokens: int = 8192,
        large_table_row_group: int = 10,
        tokenizer_model_name: str = "BAAI/bge-m3",
    ):
        self.child_target_tokens = child_target_tokens
        self.parent_max_tokens = min(parent_max_tokens, model_max_input_tokens)
        self.model_max_input_tokens = model_max_input_tokens
        self.large_table_row_group = large_table_row_group
        self.table_processor = LegalTableProcessor()
        self.hf_tokenizer = None
        self.tokenizer_name = "subword-regex-tokenizer (offline fallback)"

        if TRANSFORMERS_AVAILABLE:
            try:
                self.hf_tokenizer = AutoTokenizer.from_pretrained(tokenizer_model_name, local_files_only=False)
                self.tokenizer_name = f"HuggingFace AutoTokenizer ({tokenizer_model_name})"
            except Exception:
                self.hf_tokenizer = None

    def count_tokens(self, text: str) -> int:
        """Computes exact token count using the BGE-M3 tokenizer when available, or deterministic subword splitting."""
        if not text:
            return 0
        if self.hf_tokenizer is not None:
            return len(self.hf_tokenizer.encode(text, add_special_tokens=False, truncation=False))
        # Deterministic subword-aware tokenization: words + punctuation + numeric segments
        subwords = re.findall(r"[A-Za-z]{1,6}|\d+|[^\w\s]", text)
        return max(1, len(subwords))

    def estimate_tokens(self, text: str) -> int:
        return self.count_tokens(text)

    def build_chunks(
        self,
        parsed_doc: ParsedDocument,
        nodes: List[HierarchyNode],
        dates: List[DateRecord],
        include_table_summaries: bool = True,
    ) -> List[LegalChunk]:
        node_map: Dict[str, HierarchyNode] = {n.node_id: n for n in nodes}
        chunks: List[LegalChunk] = []
        chunk_counter = 0

        eff_date = next((d.iso for d in dates if d.role == "effective" and d.iso), None)
        exp_date = next((d.iso for d in dates if d.role == "expiration" and d.iso), None)

        # 1. Build Parent Section Chunks (preserving exact char_start..char_end slice in ParsedDocument.full_text)
        for node in nodes:
            if node.level in ("section", "schedule", "annexure") or (node.level == "article" and not node.children_ids):
                section_tree_nodes = self._collect_subtree(node, node_map)
                c_start = section_tree_nodes[0].char_start
                c_end = section_tree_nodes[-1].char_end
                verbatim_section_text = parsed_doc.full_text[c_start:c_end]

                tokens = self.count_tokens(verbatim_section_text)
                if tokens > self.parent_max_tokens:
                    # Trim on node boundaries so c_start..c_end remains an exact slice in full_text
                    included_nodes = [node]
                    for sub_n in section_tree_nodes[1:]:
                        cand_text = parsed_doc.full_text[c_start:sub_n.char_end]
                        if self.count_tokens(cand_text) <= self.parent_max_tokens:
                            included_nodes.append(sub_n)
                        else:
                            break
                    c_end = included_nodes[-1].char_end
                    verbatim_section_text = parsed_doc.full_text[c_start:c_end]
                    tokens = self.count_tokens(verbatim_section_text)

                section_path = self._build_section_path(node, node_map)
                emb_text = self._format_embedding_text(
                    doc_title=parsed_doc.filename,
                    doc_type=parsed_doc.document_type,
                    section_path=section_path,
                    content=verbatim_section_text,
                )
                chunk_counter += 1
                chunks.append(
                    LegalChunk(
                        chunk_id=f"C_{parsed_doc.document_id}_P_{chunk_counter:03d}",
                        org_id=parsed_doc.org_id,
                        case_id=parsed_doc.case_id,
                        document_id=parsed_doc.document_id,
                        document_type=parsed_doc.document_type,
                        chunk_type="parent_section",
                        node_id=node.node_id,
                        parent_id=node.parent_id,
                        clause_label=node.label,
                        section_path=section_path,
                        page=node.page_start,
                        bbox=node.bbox,
                        char_start=c_start,
                        char_end=c_end,
                        structure_confidence=node.structure_confidence,
                        clean_text=verbatim_section_text,
                        embedding_text=emb_text,
                        token_count=tokens,
                        tokenizer_name=self.tokenizer_name,
                        effective_date=eff_date,
                        expiration_date=exp_date,
                    )
                )

        # 2. Build Granular Child Chunks (leaf clauses & section bodies)
        for node in nodes:
            if node.level == "article" and node.children_ids:
                continue

            section_ancestor = self._find_section_ancestor(node, node_map)
            parent_node_id = (
                section_ancestor.node_id
                if (section_ancestor and section_ancestor.node_id != node.node_id)
                else node.parent_id
            )

            lead_in_chain = self._collect_ancestor_lead_ins(node, node_map)
            verbatim_node_text = parsed_doc.full_text[node.char_start:node.char_end]
            contextual_content = f"{lead_in_chain}\n{verbatim_node_text}" if lead_in_chain else verbatim_node_text

            section_path = self._build_section_path(node, node_map)
            emb_text = self._format_embedding_text(
                doc_title=parsed_doc.filename,
                doc_type=parsed_doc.document_type,
                section_path=section_path,
                content=contextual_content,
            )

            chunk_counter += 1
            c_type = "fallback_page" if node.level == "fallback_paragraph" else "clause"

            chunks.append(
                LegalChunk(
                    chunk_id=f"C_{parsed_doc.document_id}_{chunk_counter:03d}",
                    org_id=parsed_doc.org_id,
                    case_id=parsed_doc.case_id,
                    document_id=parsed_doc.document_id,
                    document_type=parsed_doc.document_type,
                    chunk_type=c_type,
                    node_id=node.node_id,
                    parent_id=parent_node_id,
                    clause_label=node.label,
                    section_path=section_path,
                    page=node.page_start,
                    bbox=node.bbox,
                    char_start=node.char_start,
                    char_end=node.char_end,
                    structure_confidence=node.structure_confidence,
                    clean_text=verbatim_node_text,
                    embedding_text=emb_text,
                    token_count=self.count_tokens(verbatim_node_text),
                    tokenizer_name=self.tokenizer_name,
                    effective_date=eff_date,
                    expiration_date=exp_date,
                )
            )

        # 3. Build Dual-Representation Table Chunks with exact cell-aligned spans
        for tbl in parsed_doc.tables:
            total_rows = len(tbl.rows)
            parent_nid = tbl.parent_node_id or f"N_{parsed_doc.document_id}_Schedule_1"
            section_path = [tbl.caption]
            verbatim_table_text = parsed_doc.full_text[tbl.char_start:tbl.char_end]

            if total_rows <= self.large_table_row_group:
                serialized_md = self.table_processor.serialize_rows_with_headers(tbl.caption, tbl.headers, tbl.rows)
                emb_text = self._format_embedding_text(
                    doc_title=parsed_doc.filename,
                    doc_type=parsed_doc.document_type,
                    section_path=section_path,
                    content=serialized_md,
                )
                chunks.append(
                    LegalChunk(
                        chunk_id=f"C_{parsed_doc.document_id}_TBL_{tbl.table_id}",
                        org_id=parsed_doc.org_id,
                        case_id=parsed_doc.case_id,
                        document_id=parsed_doc.document_id,
                        document_type=parsed_doc.document_type,
                        chunk_type="table_raw",
                        node_id=f"N_TBL_{tbl.table_id}",
                        parent_id=parent_nid,
                        clause_label=tbl.caption,
                        section_path=section_path,
                        page=tbl.page,
                        bbox=tbl.bbox,
                        char_start=tbl.char_start,
                        char_end=tbl.char_end,
                        structure_confidence="high",
                        clean_text=verbatim_table_text,
                        embedding_text=emb_text,
                        token_count=self.count_tokens(verbatim_table_text),
                        tokenizer_name=self.tokenizer_name,
                        table_id=tbl.table_id,
                        retrieval_aid_only=False,
                        effective_date=eff_date,
                        expiration_date=exp_date,
                    )
                )
            else:
                for grp_idx, start_r in enumerate(range(0, total_rows, self.large_table_row_group)):
                    end_r = min(total_rows, start_r + self.large_table_row_group)
                    sub_rows = tbl.rows[start_r:end_r]
                    grp_caption = f"{tbl.caption} (Rows {start_r+1}-{end_r} of {total_rows})"
                    serialized_md = self.table_processor.serialize_rows_with_headers(grp_caption, tbl.headers, sub_rows)

                    # Find exact char span of this row group in tbl.cells
                    grp_cells = [c for c in tbl.cells if start_r <= c.row_index < end_r]
                    g_start = grp_cells[0].char_start if grp_cells else tbl.char_start
                    g_end = grp_cells[-1].char_end if grp_cells else tbl.char_end
                    verbatim_grp_slice = parsed_doc.full_text[g_start:g_end]

                    emb_text = self._format_embedding_text(
                        doc_title=parsed_doc.filename,
                        doc_type=parsed_doc.document_type,
                        section_path=[grp_caption],
                        content=serialized_md,
                    )
                    chunks.append(
                        LegalChunk(
                            chunk_id=f"C_{parsed_doc.document_id}_TBL_{tbl.table_id}_G{grp_idx+1}",
                            case_id=parsed_doc.case_id,
                            document_id=parsed_doc.document_id,
                            chunk_type="table_row_group",
                            node_id=f"N_TBL_{tbl.table_id}_G{grp_idx+1}",
                            parent_id=parent_nid,
                            clause_label=grp_caption,
                            section_path=[grp_caption],
                            page=tbl.page,
                            bbox=tbl.bbox,
                            char_start=g_start,
                            char_end=g_end,
                            structure_confidence="high",
                            clean_text=verbatim_grp_slice,
                            embedding_text=emb_text,
                            token_count=self.count_tokens(verbatim_grp_slice),
                            tokenizer_name=self.tokenizer_name,
                            table_id=tbl.table_id,
                            retrieval_aid_only=False,
                            effective_date=eff_date,
                            expiration_date=exp_date,
                        )
                    )

            if include_table_summaries:
                summary_txt = self.table_processor.generate_retrieval_summary(tbl)
                emb_text = self._format_embedding_text(
                    doc_title=parsed_doc.filename,
                    doc_type=parsed_doc.document_type,
                    section_path=[f"{tbl.caption} Summary"],
                    content=summary_txt,
                )
                chunks.append(
                    LegalChunk(
                        chunk_id=f"C_{parsed_doc.document_id}_TBLSUM_{tbl.table_id}",
                        org_id=parsed_doc.org_id,
                        case_id=parsed_doc.case_id,
                        document_id=parsed_doc.document_id,
                        document_type=parsed_doc.document_type,
                        chunk_type="table_summary",
                        node_id=f"N_TBLSUM_{tbl.table_id}",
                        parent_id=parent_nid,
                        clause_label=f"{tbl.caption} (Summary)",
                        section_path=[tbl.caption],
                        page=tbl.page,
                        bbox=tbl.bbox,
                        char_start=tbl.char_start,
                        char_end=tbl.char_end,
                        structure_confidence="high",
                        clean_text=summary_txt,
                        embedding_text=emb_text,
                        token_count=self.count_tokens(summary_txt),
                        tokenizer_name=self.tokenizer_name,
                        table_id=tbl.table_id,
                        retrieval_aid_only=True,
                        effective_date=eff_date,
                        expiration_date=exp_date,
                    )
                )

        return chunks

    def _collect_subtree(self, root: HierarchyNode, node_map: Dict[str, HierarchyNode]) -> List[HierarchyNode]:
        result = [root]
        for cid in root.children_ids:
            if cid in node_map:
                result.extend(self._collect_subtree(node_map[cid], node_map))
        return result

    @staticmethod
    def _find_section_ancestor(node: HierarchyNode, node_map: Dict[str, HierarchyNode]) -> Optional[HierarchyNode]:
        curr = node
        while curr.parent_id and curr.parent_id in node_map:
            parent = node_map[curr.parent_id]
            if parent.level in ("section", "schedule", "annexure"):
                return parent
            curr = parent
        return None

    @staticmethod
    def _collect_ancestor_lead_ins(node: HierarchyNode, node_map: Dict[str, HierarchyNode]) -> str:
        lead_ins: List[str] = []
        curr = node
        while curr.parent_id and curr.parent_id in node_map:
            parent = node_map[curr.parent_id]
            if parent.lead_in_text:
                lead_ins.append(f"[Context from {parent.label}]: {parent.lead_in_text}")
            if parent.level in ("section", "article"):
                break
            curr = parent
        lead_ins.reverse()
        return "\n".join(lead_ins)

    @staticmethod
    def _build_section_path(node: HierarchyNode, node_map: Dict[str, HierarchyNode]) -> List[str]:
        path: List[str] = []
        curr: Optional[HierarchyNode] = node
        while curr is not None:
            hdr = f"{curr.label} ({curr.title})" if curr.title and curr.title != curr.label else curr.label
            path.append(hdr)
            curr = node_map.get(curr.parent_id) if curr.parent_id else None
        path.reverse()
        return path

    @staticmethod
    def _format_embedding_text(doc_title: str, doc_type: str, section_path: List[str], content: str) -> str:
        hierarchy_str = " > ".join(section_path)
        if len(content) > 24000:
            content = content[:24000]
        return (
            f"Document: {doc_title}\n"
            f"Document Type: {doc_type}\n\n"
            f"Hierarchy:\n{hierarchy_str}\n\n"
            f"Content:\n{content}"
        )
