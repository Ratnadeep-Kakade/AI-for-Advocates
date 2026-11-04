"""
Module 4: Components 2, 3, 4, 5, 6 — Logical Unit Reconstruction & Deterministic Legal Structural Processor
Updated per Technical Audit:
- Priority 4: Adds `LogicalUnitReconstructor` preprocessing layer that merges split headings,
  introductory lead-ins, and continuation blocks while preserving original `TextBlock`s, page
  boundaries, and exact `ParsedDocument.full_text[char_start:char_end]` offsets.
- Priority 2A/2B: `DefinitionsExtractor` stores exact verbatim source slices in `DefinitionEntry.definition`
  and normalized explanations in `DefinitionEntry.extracted_meaning`.
- Priority 5: Upgrades `CrossReferenceExtractor` to support `Section 4`, `Clause 4.2`, `Section 4.2(b)`,
  `Clause 4.2(b)(ii)`, `Article 7` (Arabic <-> Roman conversion), `Schedule I` / `Schedule II`,
  `Annexure A`, and inverted references like `Sub-clause (b) of Clause 4.2`, with explicit
  `RESOLVED`, `UNRESOLVED`, `AMBIGUOUS`, and `EXTERNAL_STATUTE` statuses and exact character provenance.
- Priority 2D: `LegalTableProcessor` preserves cell-level provenance (`TableCellProvenance`) and stores
  calculated pandas aggregations strictly in `derived_annotations` rather than mutating source text.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import pandas as pd

from .schemas import (
    ParsedDocument,
    TextBlock,
    LogicalTextUnit,
    HierarchyNode,
    DefinitionEntry,
    CrossReferenceEdge,
    DateRecord,
    RawTable,
    TableCellProvenance,
)

try:
    import dateparser
    DATEPARSER_AVAILABLE = True
except ImportError:
    DATEPARSER_AVAILABLE = False


# ============================================================================
# ROMAN <-> ARABIC NUMERAL CONVERSION HELPERS
# ============================================================================

ROMAN_TO_INT_MAP = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
}
INT_TO_ROMAN_MAP = {v: k for k, v in ROMAN_TO_INT_MAP.items()}


def normalize_roman_or_int(token: str) -> Tuple[str, Optional[str]]:
    """Returns (primary_token, alternate_roman_or_arabic_token)."""
    t = token.strip().upper()
    if t in ROMAN_TO_INT_MAP:
        return t, str(ROMAN_TO_INT_MAP[t])
    if t.isdigit() and int(t) in INT_TO_ROMAN_MAP:
        return t, INT_TO_ROMAN_MAP[int(t)]
    return token.strip(), None


# ============================================================================
# PRIORITY 4: LOGICAL TEXT UNIT RECONSTRUCTOR (PREPROCESSING LAYER)
# ============================================================================

class LogicalUnitReconstructor:
    """
    Reconstructs logical paragraphs and heading+lead-in units from raw Docling `TextBlock`s
    before passing them to `LegalHierarchyParser`.
    Guarantees:
    1. Original `parsed_doc.text_blocks` are preserved unmodified.
    2. Split headings (e.g., Block 1: 'ARTICLE I', Block 2: 'DEFINITIONS AND INTERPRETATION')
       and split clause lead-ins (e.g., Block 1: '4.2 Contractual Liability Cap...', Block 2:
       'The following exceptions apply:') are merged into a single `LogicalTextUnit`.
    3. Never merges across unrelated clauses or across page boundaries unless a sentence is
       explicitly unfinished.
    4. `unit.text` is strictly equal to `parsed_doc.full_text[unit.char_start:unit.char_end]`.
    """

    BARE_HEADING_RE = re.compile(
        r"^(?:ARTICLE\s+(?:[IVXLCDM]+|\d+)|Schedule\s+(?:[IVXLCDM]+|\d+|[A-Z])|Annexure\s+(?:[A-Z]|\d+)|\d+(?:\.\d+)*\.?|\([a-zA-Z0-9]+\))$",
        re.IGNORECASE,
    )
    NEW_STRUCTURAL_START_RE = re.compile(
        r"^(?:ARTICLE\s+(?:[IVXLCDM]+|\d+)|Schedule\s+(?:[IVXLCDM]+|\d+|[A-Z])|Annexure\s+(?:[A-Z]|\d+)|\d+\.\d+(?:\.\d+)*\b|\d+\.\s+|\([a-zA-Z]+\)\s+)",
        re.IGNORECASE,
    )
    ALL_CAPS_TITLE_RE = re.compile(r"^[A-Z0-9\s,\-&]{4,100}$")

    def reconstruct_logical_units(self, parsed_doc: ParsedDocument) -> List[LogicalTextUnit]:
        blocks = parsed_doc.text_blocks
        if not blocks:
            return []

        units: List[LogicalTextUnit] = []
        idx = 0
        n = len(blocks)

        while idx < n:
            curr = blocks[idx]
            merged_blocks = [curr]
            curr_text = curr.text.strip()

            while idx + 1 < n:
                nxt = blocks[idx + 1]
                nxt_text = nxt.text.strip()

                # Rule 1: Bare structural header (e.g. 'ARTICLE I') followed on same page by its title ('DEFINITIONS AND INTERPRETATION')
                if (
                    curr.page == nxt.page
                    and self.BARE_HEADING_RE.match(curr_text)
                    and not self.NEW_STRUCTURAL_START_RE.match(nxt_text)
                ):
                    merged_blocks.append(nxt)
                    idx += 1
                    curr_text = parsed_doc.full_text[merged_blocks[0].char_start:merged_blocks[-1].char_end]
                    continue

                # Rule 2: A numbered section/clause block followed on the same page by an unnumbered lead-in sentence
                # (e.g., 'The following exceptions apply:') or continuation sentence that is not a new structural node
                if (
                    curr.page == nxt.page
                    and self.NEW_STRUCTURAL_START_RE.match(merged_blocks[0].text.strip())
                    and not self.NEW_STRUCTURAL_START_RE.match(nxt_text)
                    and not self.ALL_CAPS_TITLE_RE.match(nxt_text)
                    and (nxt_text.endswith(":") or not curr_text.endswith((".", ";", ":", '"', ")")))
                ):
                    merged_blocks.append(nxt)
                    idx += 1
                    curr_text = parsed_doc.full_text[merged_blocks[0].char_start:merged_blocks[-1].char_end]
                    continue

                break

            c_start = merged_blocks[0].char_start
            c_end = merged_blocks[-1].char_end
            exact_slice = parsed_doc.full_text[c_start:c_end]

            units.append(
                LogicalTextUnit(
                    unit_id=f"LU_{parsed_doc.document_id}_{len(units)+1:04d}",
                    document_id=parsed_doc.document_id,
                    source_block_ids=[b.block_id for b in merged_blocks],
                    page_start=merged_blocks[0].page,
                    page_end=merged_blocks[-1].page,
                    char_start=c_start,
                    char_end=c_end,
                    bbox=merged_blocks[0].bbox,
                    text=exact_slice,
                    reconstructed_from_multiple_blocks=(len(merged_blocks) > 1),
                )
            )
            idx += 1

        return units


# ============================================================================
# COMPONENT 2: CUSTOM LEGAL HIERARCHY PARSER
# ============================================================================

class LegalHierarchyParser:
    """
    Deterministic numbering parser constructing a hierarchical AST of legal clauses
    from reconstructed `LogicalTextUnit`s.
    Supports:
    - ARTICLE I..XV / ARTICLE 1..15
    - Top-level numbered clauses: 1., 2., 3., 4.
    - Multi-level numbered sections: 4.1, 4.1.1
    - Lettered clauses: (a), (b)
    - Roman numeral subclauses: (i), (ii), (iii)
    - Uppercase lettered sub-subclauses: (A), (B)
    - Schedules (Schedule 1, Schedule I, Schedule A) & Annexures (Annexure A, Annexure 1)
    """

    ROMAN_UPPER_SET = set(ROMAN_TO_INT_MAP.keys())
    ROMAN_LOWER_SET = {k.lower() for k in ROMAN_TO_INT_MAP.keys()}

    PATTERNS = [
        ("article", 1, re.compile(r"^(ARTICLE\s+([IVXLCDM]+|\d+))\b\s*(.*)$", re.IGNORECASE | re.DOTALL)),
        ("schedule", 1, re.compile(r"^(Schedule\s+([IVXLCDM]+|\d+|[A-Z]))\b\s*(.*)$", re.IGNORECASE | re.DOTALL)),
        ("annexure", 1, re.compile(r"^(Annexure\s+([A-Z]|\d+))\b\s*(.*)$", re.IGNORECASE | re.DOTALL)),
        ("sub_section", 3, re.compile(r"^(\d+\.\d+\.\d+)\s+(.*)$", re.DOTALL)),
        ("section", 2, re.compile(r"^(\d+\.\d+)\s+(.*)$", re.DOTALL)),
        ("top_numbered", 2, re.compile(r"^(\d+)\.\s+(.*)$", re.DOTALL)),
        ("paren_token", 0, re.compile(r"^\(([a-zA-Z]+)\)\s+(.*)$", re.DOTALL)),
    ]

    def __init__(self):
        self.reconstructor = LogicalUnitReconstructor()

    def parse_hierarchy(self, parsed_doc: ParsedDocument) -> Tuple[List[HierarchyNode], str, List[str]]:
        logical_units = self.reconstructor.reconstruct_logical_units(parsed_doc)
        nodes: List[HierarchyNode] = []
        warnings: List[str] = []
        active_stack: Dict[int, HierarchyNode] = {}
        orphan_count = 0
        numbered_count = 0

        reconstructed_count = sum(1 for u in logical_units if u.reconstructed_from_multiple_blocks)
        if reconstructed_count > 0:
            parsed_doc.metadata["reconstructed_logical_units"] = reconstructed_count

        for idx, unit in enumerate(logical_units):
            txt = unit.text
            if not txt.strip():
                continue

            level, depth, raw_num, title, _ = self._classify_unit(txt, active_stack)
            if level == "preamble":
                node_id = f"N_{parsed_doc.document_id}_PRE_{idx+1}"
                nodes.append(
                    HierarchyNode(
                        node_id=node_id,
                        level="preamble",
                        depth=0,
                        label="Preamble",
                        raw_number="",
                        title="Document Title & Preamble",
                        text=txt,
                        lead_in_text=self._extract_lead_in(txt),
                        parent_id=None,
                        children_ids=[],
                        document_id=parsed_doc.document_id,
                        page_start=unit.page_start,
                        page_end=unit.page_end,
                        char_start=unit.char_start,
                        char_end=unit.char_end,
                        bbox=unit.bbox,
                        structure_confidence="high",
                        is_orphan=False,
                        source_block_ids=unit.source_block_ids,
                    )
                )
                continue

            numbered_count += 1
            parent_node: Optional[HierarchyNode] = None
            is_orphan = False

            if depth == 1:
                parent_node = None
            else:
                parent_node = active_stack.get(depth - 1)
                if parent_node is None:
                    # Allow top_numbered (e.g. '4.') at depth 2 without an Article if document uses numbered sections at root
                    if level == "top_numbered" and 1 not in active_stack:
                        depth = 1
                        parent_node = None
                    else:
                        for d in range(depth - 2, 0, -1):
                            if d in active_stack:
                                parent_node = active_stack[d]
                                break
                        is_orphan = True
                        orphan_count += 1
                        warnings.append(
                            f"Orphan/numbering jump detected at unit '{raw_num}' on page {unit.page_start}: missing expected parent at depth {depth - 1}."
                        )

            if level == "sub_section":
                sec_prefix = ".".join(raw_num.split(".")[:2])
                if not parent_node or parent_node.raw_number != sec_prefix:
                    is_orphan = True
                    orphan_count += 1
                    warnings.append(
                        f"Numbering inconsistency: Sub-section '{raw_num}' appeared without parent Section '{sec_prefix}'."
                    )

            comp_label = self._build_composite_label(level, raw_num, parent_node)
            safe_id_suffix = re.sub(r"[^a-zA-Z0-9]+", "_", comp_label).strip("_")
            node_id = f"N_{parsed_doc.document_id}_{safe_id_suffix}"

            node = HierarchyNode(
                node_id=node_id,
                level=level,
                depth=depth,
                label=comp_label,
                raw_number=raw_num,
                title=title,
                text=txt,
                lead_in_text=self._extract_lead_in(txt),
                parent_id=parent_node.node_id if parent_node else None,
                children_ids=[],
                document_id=parsed_doc.document_id,
                page_start=unit.page_start,
                page_end=unit.page_end,
                char_start=unit.char_start,
                char_end=unit.char_end,
                bbox=unit.bbox,
                structure_confidence="low" if is_orphan else "high",
                is_orphan=is_orphan,
                source_block_ids=unit.source_block_ids,
            )

            if parent_node is not None:
                parent_node.children_ids.append(node.node_id)
                parent_node.page_end = max(parent_node.page_end, unit.page_end)

            active_stack[depth] = node
            for deeper in [k for k in active_stack.keys() if k > depth]:
                del active_stack[deeper]

            nodes.append(node)

        if numbered_count == 0 or (orphan_count / max(numbered_count, 1)) > 0.30:
            warnings.append(
                f"Hierarchy validation failed (orphan ratio {orphan_count}/{numbered_count}). "
                "Falling back to deterministic page/paragraph-level chunks with structure_confidence='low'."
            )
            fallback_nodes = self._build_fallback_nodes(parsed_doc)
            parsed_doc.parsing_warnings.extend(warnings)
            return fallback_nodes, "low", warnings

        parsed_doc.parsing_warnings.extend(warnings)
        return nodes, "high", warnings

    def _classify_unit(
        self, txt: str, active_stack: Dict[int, HierarchyNode]
    ) -> Tuple[str, int, str, str, str]:
        s_txt = txt.strip()
        for name, base_depth, pattern in self.PATTERNS:
            m = pattern.match(s_txt)
            if not m:
                continue
            if name in ("article", "schedule", "annexure"):
                full_hdr = re.sub(r"\s+", " ", m.group(1).strip())
                rest = re.sub(r"\s+", " ", m.group(3).strip())
                return name, 1, full_hdr, rest[:80] if rest else full_hdr, txt
            if name in ("sub_section", "section", "top_numbered"):
                num_str = m.group(1).strip()
                rest = re.sub(r"\s+", " ", m.group(2).strip())
                title = rest.split(".")[0].strip() if "." in rest[:75] else rest[:60]
                return name, base_depth, num_str, title, txt
            if name == "paren_token":
                token = m.group(1)
                rest = re.sub(r"\s+", " ", m.group(2).strip())
                title = rest.split(".")[0].strip() if "." in rest[:65] else rest[:50]
                if token in self.ROMAN_LOWER_SET and (
                    token != "i" or (3 in active_stack and active_stack[3].raw_number in ("(a)", "(b)", "(c)", "(d)", "(e)", "(f)", "(g)", "(h)"))
                ):
                    return "subclause", 4, f"({token})", title, txt
                elif token.islower() and len(token) == 1:
                    return "clause", 3, f"({token})", title, txt
                elif token.isupper() and len(token) == 1:
                    return "sub_subclause", 5, f"({token})", title, txt
        return "preamble", 0, "", "Preamble", txt

    @staticmethod
    def _build_composite_label(level: str, raw_num: str, parent: Optional[HierarchyNode]) -> str:
        if level in ("article", "schedule", "annexure", "section", "sub_section", "top_numbered"):
            return raw_num
        if parent and parent.level in ("section", "sub_section", "top_numbered", "clause", "subclause"):
            return f"{parent.label}{raw_num}"
        return raw_num

    @staticmethod
    def _extract_lead_in(txt: str) -> str:
        stripped = txt.strip()
        if stripped.endswith(":"):
            return stripped.split("\n")[-1].strip()
        return ""

    @staticmethod
    def _build_fallback_nodes(parsed_doc: ParsedDocument) -> List[HierarchyNode]:
        fallback_nodes: List[HierarchyNode] = []
        for idx, block in enumerate(parsed_doc.text_blocks):
            fallback_nodes.append(
                HierarchyNode(
                    node_id=f"N_{parsed_doc.document_id}_FALLBACK_P{block.page}_{idx+1}",
                    level="fallback_paragraph",
                    depth=1,
                    label=f"Page_{block.page}_Para_{idx+1}",
                    raw_number="",
                    title=f"Page {block.page} Paragraph {idx+1}",
                    text=block.text,
                    lead_in_text="",
                    parent_id=None,
                    children_ids=[],
                    document_id=parsed_doc.document_id,
                    page_start=block.page,
                    page_end=block.page,
                    char_start=block.char_start,
                    char_end=block.char_end,
                    bbox=block.bbox,
                    structure_confidence="low",
                    is_orphan=True,
                    source_block_ids=[block.block_id],
                )
            )
        return fallback_nodes


# ============================================================================
# COMPONENT 3: DEFINITIONS MAP EXTRACTOR (STRICT VERBATIM SOURCE SPANS)
# ============================================================================

class DefinitionsExtractor:
    """
    Deterministic legal definition extractor.
    CRITICAL PROVENANCE GUARANTEE:
    `DefinitionEntry.definition` ALWAYS stores the exact verbatim slice
    `parsed_doc.full_text[char_start:char_end]`, while `extracted_meaning` stores
    the normalized explanation.
    """

    MEANS_RE = re.compile(
        r'"([A-Z][A-Za-z0-9\s\-]{1,45})"\s+(shall\s+mean|means)\s+(.+)$',
        re.DOTALL,
    )
    INLINE_THE_RE = re.compile(
        r'([A-Z][A-Za-z0-9\s,\.&\-]{3,80}?)\s*\(\s*(?:this|the)\s+"([A-Z][A-Za-z0-9\s\-]{1,35})"\s*\)'
    )
    HEREINAFTER_RE = re.compile(
        r'([A-Za-z0-9\s,\.&\-]{5,80}?)\s*\(\s*hereinafter\s+referred\s+to\s+as\s+(?:the\s+)?"([A-Z][A-Za-z0-9\s\-]{1,35})"\s*\)',
        re.IGNORECASE,
    )

    def extract_definitions(self, parsed_doc: ParsedDocument, nodes: List[HierarchyNode]) -> List[DefinitionEntry]:
        entries: List[DefinitionEntry] = []
        seen_in_doc: set = set()

        for node in nodes:
            txt = node.text

            # Pattern 1 & 2: "X" means / "X" shall mean
            m_means = self.MEANS_RE.search(txt)
            if m_means:
                term = m_means.group(1).strip()
                pat_verb = m_means.group(2).lower()
                pat_type = "shall_mean" if "shall" in pat_verb else "means"
                c_start = node.char_start + m_means.start()
                c_end = node.char_start + m_means.end()
                verbatim_slice = parsed_doc.full_text[c_start:c_end]
                if term.lower() not in seen_in_doc:
                    seen_in_doc.add(term.lower())
                    entries.append(
                        DefinitionEntry(
                            term=term,
                            definition=verbatim_slice,
                            extracted_meaning=m_means.group(3).strip(),
                            pattern_type=pat_type,
                            document_id=parsed_doc.document_id,
                            case_id=parsed_doc.case_id,
                            node_id=node.node_id,
                            page=node.page_start,
                            char_start=c_start,
                            char_end=c_end,
                        )
                    )

            # Pattern 3: Entity Name (the "Company")
            for m_in in self.INLINE_THE_RE.finditer(txt):
                entity_desc = m_in.group(1).strip(" ,")
                term = m_in.group(2).strip()
                c_start = node.char_start + m_in.start()
                c_end = node.char_start + m_in.end()
                verbatim_slice = parsed_doc.full_text[c_start:c_end]
                if term.lower() not in seen_in_doc:
                    seen_in_doc.add(term.lower())
                    entries.append(
                        DefinitionEntry(
                            term=term,
                            definition=verbatim_slice,
                            extracted_meaning=f'"{term}" refers to {entity_desc}',
                            pattern_type="inline_parenthetical",
                            document_id=parsed_doc.document_id,
                            case_id=parsed_doc.case_id,
                            node_id=node.node_id,
                            page=node.page_start,
                            char_start=c_start,
                            char_end=c_end,
                        )
                    )

            # Pattern 4: (hereinafter referred to as "Founders")
            for m_here in self.HEREINAFTER_RE.finditer(txt):
                entity_desc = m_here.group(1).strip(" ,")
                term = m_here.group(2).strip()
                c_start = node.char_start + m_here.start()
                c_end = node.char_start + m_here.end()
                verbatim_slice = parsed_doc.full_text[c_start:c_end]
                if term.lower() not in seen_in_doc:
                    seen_in_doc.add(term.lower())
                    entries.append(
                        DefinitionEntry(
                            term=term,
                            definition=verbatim_slice,
                            extracted_meaning=f'"{term}" refers to {entity_desc}',
                            pattern_type="hereinafter",
                            document_id=parsed_doc.document_id,
                            case_id=parsed_doc.case_id,
                            node_id=node.node_id,
                            page=node.page_start,
                            char_start=c_start,
                            char_end=c_end,
                        )
                    )

        return entries


# ============================================================================
# COMPONENT 4: ENHANCED CROSS-REFERENCE EXTRACTOR & RESOLVER (PRIORITY 5)
# ============================================================================

class CrossReferenceExtractor:
    """
    Priority 5: Enhanced Cross-Reference Extractor.
    Identifies and normalizes:
    - Section 4, Clause 4.2, Section 4.2(b), Clause 4.2(b)(ii)
    - Article 7 / Article VII (bidirectional Roman <-> Arabic normalization)
    - Schedule 1 / Schedule I / Schedule II
    - Annexure A
    - Inverted nested references: 'Sub-clause (b) of Clause 4.2', 'paragraph (ii) of Section 4.2(b)'
    - Ambiguous standalone clause references: 'Clause (a)' when multiple sections contain '(a)' -> AMBIGUOUS
    Assigns explicit resolution_status: RESOLVED, UNRESOLVED, AMBIGUOUS, EXTERNAL_STATUTE.
    """

    EXTERNAL_STATUTE_RE = re.compile(
        r"\b(Section\s+\d+[A-Za-z0-9\-]*\s+of\s+the\s+(?:Delaware\s+General\s+Corporation\s+Law|Internal\s+Revenue\s+Code|Securities\s+Act(?:\s+of\s+\d{4})?))",
        re.IGNORECASE,
    )

    # Inverted nested pattern: "Sub-clause (b) of Clause 4.2" or "paragraph (ii) of Section 4.2(b)"
    INVERTED_NESTED_RE = re.compile(
        r"\b((?:Sub-clause|Subclause|Clause|Paragraph)\s+(\([a-zA-Z0-9]+\)(?:\([a-zA-Z0-9]+\))*)\s+of\s+(?:Section|Clause|Article)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*))",
        re.IGNORECASE,
    )

    INTERNAL_XREF_PATTERNS = [
        (
            "subject_to",
            re.compile(
                r"\b(Subject\s+to\s+(Section|Clause|Article|Schedule|Annexure|Sub-clause)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*|\([a-zA-Z0-9]+\)|[IVXLCDM]+|[A-Z]))",
                re.IGNORECASE,
            ),
        ),
        (
            "notwithstanding",
            re.compile(
                r"\b(Notwithstanding\s+(Section|Clause|Article)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*|[IVXLCDM]+)(?:\s+and\s+(Section|Clause|Sub-clause)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*))?)",
                re.IGNORECASE,
            ),
        ),
        (
            "schedule",
            re.compile(
                r"\b((?:In\s+accordance\s+with\s+|listed\s+on\s+|forth\s+in\s+(?:detail\s+in\s+)?)?(Schedule\s+(?:[IVXLCDM]+|\d+|[A-Z])\b))",
                re.IGNORECASE,
            ),
        ),
        (
            "annexure",
            re.compile(
                r"\b((?:under\s+|in\s+accordance\s+with\s+)?(Annexure\s+(?:[A-Z]|\d+)\b))",
                re.IGNORECASE,
            ),
        ),
        (
            "refers_to",
            re.compile(
                r"\b((?:As\s+provided\s+under|pursuant\s+to|under|in\s+accordance\s+with|of|in)\s+(?:this\s+)?(Article|Section|Clause)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*|\([a-zA-Z0-9]+\)|[IVXLCDM]+)(?:,\s*(Clause|Section)\s+([0-9]+(?:\.[0-9]+)*(?:\([a-zA-Z0-9]+\))*))?)",
                re.IGNORECASE,
            ),
        ),
    ]

    def extract_cross_references(
        self, parsed_doc: ParsedDocument, nodes: List[HierarchyNode]
    ) -> List[CrossReferenceEdge]:
        # Build lookup maps: exact normalized label -> node_id, and raw_number -> list of node_ids (for ambiguity detection)
        label_map: Dict[str, str] = {}
        raw_num_map: Dict[str, List[str]] = {}

        for n in nodes:
            lbl_low = n.label.lower()
            label_map[lbl_low] = n.node_id
            if n.raw_number:
                raw_num_map.setdefault(n.raw_number.lower(), []).append(n.node_id)

            # Register Roman <-> Arabic aliases for Articles and Schedules
            if n.level in ("article", "schedule", "annexure"):
                parts = n.label.split()
                if len(parts) == 2:
                    prefix, num_tok = parts[0], parts[1]
                    pri, alt = normalize_roman_or_int(num_tok)
                    label_map[f"{prefix} {pri}".lower()] = n.node_id
                    if alt:
                        label_map[f"{prefix} {alt}".lower()] = n.node_id
            elif n.level in ("section", "sub_section", "top_numbered"):
                label_map[f"section {n.label}".lower()] = n.node_id
                label_map[f"clause {n.label}".lower()] = n.node_id
            elif n.level in ("clause", "subclause", "sub_subclause"):
                label_map[f"clause {n.label}".lower()] = n.node_id
                label_map[f"section {n.label}".lower()] = n.node_id

        edges: List[CrossReferenceEdge] = []
        edge_counter = 0
        seen_keys: set = set()

        for node in nodes:
            txt = node.text
            occupied_spans: List[Tuple[int, int]] = []

            # 1. External statutory references
            for m_ext in self.EXTERNAL_STATUTE_RE.finditer(txt):
                occupied_spans.append((m_ext.start(), m_ext.end()))
                edge_counter += 1
                citation = m_ext.group(1).strip()
                c_start = node.char_start + m_ext.start(1)
                c_end = node.char_start + m_ext.end(1)
                edges.append(
                    CrossReferenceEdge(
                        edge_id=f"XREF_{parsed_doc.document_id}_{edge_counter:03d}",
                        document_id=parsed_doc.document_id,
                        case_id=parsed_doc.case_id,
                        from_node=node.node_id,
                        to_node=None,
                        target_label=citation,
                        normalized_reference=citation,
                        type="external_statute",
                        raw_text=citation,
                        resolution_status="EXTERNAL_STATUTE",
                        resolved=False,
                        is_external=True,
                        external_citation=citation,
                        candidate_target_nodes=[],
                        source_provenance={
                            "document_id": parsed_doc.document_id,
                            "node_id": node.node_id,
                            "page": node.page_start,
                            "char_start": c_start,
                            "char_end": c_end,
                        },
                    )
                )

            # 2. Inverted nested references ("Sub-clause (b) of Clause 4.2" -> "4.2(b)")
            for m_inv in self.INVERTED_NESTED_RE.finditer(txt):
                occupied_spans.append((m_inv.start(), m_inv.end()))
                raw_match = m_inv.group(1).strip()
                sub_part = m_inv.group(2).strip()
                parent_part = m_inv.group(3).strip()
                norm_ref = f"{parent_part}{sub_part}"
                c_start = node.char_start + m_inv.start(1)
                c_end = node.char_start + m_inv.end(1)

                to_node, status, candidates = self._resolve_target(norm_ref, label_map, raw_num_map)
                if to_node == node.node_id:
                    continue
                dedup_key = (node.node_id, norm_ref.lower(), "refers_to")
                if dedup_key not in seen_keys:
                    seen_keys.add(dedup_key)
                    edge_counter += 1
                    edges.append(
                        CrossReferenceEdge(
                            edge_id=f"XREF_{parsed_doc.document_id}_{edge_counter:03d}",
                            document_id=parsed_doc.document_id,
                            case_id=parsed_doc.case_id,
                            from_node=node.node_id,
                            to_node=to_node,
                            target_label=norm_ref,
                            normalized_reference=norm_ref,
                            type="refers_to",
                            raw_text=raw_match,
                            resolution_status=status,
                            resolved=(status == "RESOLVED"),
                            is_external=False,
                            external_citation=None,
                            candidate_target_nodes=candidates,
                            source_provenance={
                                "document_id": parsed_doc.document_id,
                                "node_id": node.node_id,
                                "page": node.page_start,
                                "char_start": c_start,
                                "char_end": c_end,
                            },
                        )
                    )

            # 3. Standard & compound internal references
            for ref_type, pattern in self.INTERNAL_XREF_PATTERNS:
                for m in pattern.finditer(txt):
                    if any(not (m.end() <= s or m.start() >= e) for s, e in occupied_spans):
                        continue

                    raw_match = m.group(1).strip()
                    c_start = node.char_start + m.start(1)
                    c_end = node.char_start + m.end(1)

                    targets: List[Tuple[str, str]] = []  # (kind, ident)
                    if ref_type in ("schedule", "annexure"):
                        parts = m.group(2).strip().split()
                        targets.append((parts[0], parts[1]))
                    else:
                        kind = m.group(2).strip()
                        ident = m.group(3).strip()
                        targets.append((kind, ident))
                        if len(m.groups()) >= 5 and m.group(5):
                            targets.append((m.group(4).strip(), m.group(5).strip()))

                    for kind, ident in targets:
                        norm_ref = self._normalize_reference(kind, ident, label_map)
                        to_node, status, candidates = self._resolve_target(norm_ref, label_map, raw_num_map)
                        if to_node == node.node_id:
                            continue
                        dedup_key = (node.node_id, norm_ref.lower(), ref_type)
                        if dedup_key in seen_keys:
                            continue
                        seen_keys.add(dedup_key)
                        edge_counter += 1
                        edges.append(
                            CrossReferenceEdge(
                                edge_id=f"XREF_{parsed_doc.document_id}_{edge_counter:03d}",
                                document_id=parsed_doc.document_id,
                                case_id=parsed_doc.case_id,
                                from_node=node.node_id,
                                to_node=to_node,
                                target_label=norm_ref,
                                normalized_reference=norm_ref,
                                type=ref_type,
                                raw_text=raw_match,
                                resolution_status=status,
                                resolved=(status == "RESOLVED"),
                                is_external=False,
                                external_citation=None,
                                candidate_target_nodes=candidates,
                                source_provenance={
                                    "document_id": parsed_doc.document_id,
                                    "node_id": node.node_id,
                                    "page": node.page_start,
                                    "char_start": c_start,
                                    "char_end": c_end,
                                },
                            )
                        )

        return edges

    @staticmethod
    def _normalize_reference(kind: str, ident: str, label_map: Dict[str, str]) -> str:
        k_low = kind.lower()
        id_clean = ident.strip()
        if k_low == "article":
            pri, alt = normalize_roman_or_int(id_clean)
            if f"article {pri}".lower() in label_map:
                return f"ARTICLE {pri}"
            if alt and f"article {alt}".lower() in label_map:
                return f"ARTICLE {alt}"
            return f"ARTICLE {pri}"
        if k_low == "schedule":
            pri, alt = normalize_roman_or_int(id_clean)
            if f"schedule {pri}".lower() in label_map:
                return f"Schedule {pri}"
            if alt and f"schedule {alt}".lower() in label_map:
                return f"Schedule {alt}"
            return f"Schedule {pri}"
        if k_low == "annexure":
            return f"Annexure {id_clean.upper()}"
        return id_clean

    @staticmethod
    def _resolve_target(
        norm_ref: str,
        label_map: Dict[str, str],
        raw_num_map: Dict[str, List[str]],
    ) -> Tuple[Optional[str], str, List[str]]:
        ref_low = norm_ref.lower()
        if ref_low in label_map:
            nid = label_map[ref_low]
            return nid, "RESOLVED", [nid]

        # Check if it's a bare parenthetical reference like '(a)' or '(b)' that matches multiple nodes
        if ref_low in raw_num_map:
            candidates = raw_num_map[ref_low]
            if len(candidates) == 1:
                return candidates[0], "RESOLVED", candidates
            elif len(candidates) > 1:
                return None, "AMBIGUOUS", candidates

        return None, "UNRESOLVED", []


# ============================================================================
# COMPONENT 5: DETERMINISTIC DATE EXTRACTOR
# ============================================================================

class LegalDateExtractor:
    EXPLICIT_DATE_RE = re.compile(
        r"\b(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{4})\b",
        re.IGNORECASE,
    )
    SLASH_DATE_RE = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
    RELATIVE_DATE_RE = re.compile(
        r"\b((?:Thirty|Sixty|Ninety|Fifteen|\d+)\s*(?:\(\d+\))?\s*days\s+after\s+the\s+(Effective|Execution)\s+Date)\b",
        re.IGNORECASE,
    )

    WORD_TO_INT = {
        "fifteen": 15,
        "thirty": 30,
        "sixty": 60,
        "ninety": 90,
    }

    def extract_dates(self, parsed_doc: ParsedDocument, nodes: List[HierarchyNode]) -> List[DateRecord]:
        records: List[DateRecord] = []
        anchor_dates: Dict[str, str] = {}
        counter = 0

        for node in nodes:
            txt = node.text
            for m in self.EXPLICIT_DATE_RE.finditer(txt):
                raw_date = m.group(1)
                iso_str = self._parse_explicit_date(raw_date)
                context_window = txt[max(0, m.start() - 65):min(len(txt), m.end() + 45)]
                role, conf = self._infer_role(context_window)
                if role in ("effective", "execution") and iso_str:
                    anchor_dates[role] = iso_str

                counter += 1
                records.append(
                    DateRecord(
                        date_id=f"DT_{parsed_doc.document_id}_{counter:03d}",
                        document_id=parsed_doc.document_id,
                        case_id=parsed_doc.case_id,
                        iso=iso_str,
                        raw=raw_date,
                        role=role,
                        node_id=node.node_id,
                        page=node.page_start,
                        char_start=node.char_start + m.start(),
                        char_end=node.char_start + m.end(),
                        ambiguous=False,
                        derived=False,
                        derivation_rule=None,
                        role_confidence=conf,
                    )
                )

            for m_slash in self.SLASH_DATE_RE.finditer(txt):
                raw_slash = m_slash.group(0)
                d1, d2, yr = int(m_slash.group(1)), int(m_slash.group(2)), int(m_slash.group(3))
                is_ambig = (d1 <= 12 and d2 <= 12 and d1 != d2)
                iso_val = None if is_ambig else f"{yr:04d}-{d1:02d}-{d2:02d}"
                context_window = txt[max(0, m_slash.start() - 65):min(len(txt), m_slash.end() + 45)]
                role, conf = self._infer_role(context_window)
                counter += 1
                records.append(
                    DateRecord(
                        date_id=f"DT_{parsed_doc.document_id}_{counter:03d}",
                        document_id=parsed_doc.document_id,
                        case_id=parsed_doc.case_id,
                        iso=iso_val,
                        raw=raw_slash,
                        role=role,
                        node_id=node.node_id,
                        page=node.page_start,
                        char_start=node.char_start + m_slash.start(),
                        char_end=node.char_start + m_slash.end(),
                        ambiguous=is_ambig,
                        derived=False,
                        derivation_rule="Unresolved MM/DD vs DD/MM format without explicit jurisdictional date convention" if is_ambig else None,
                        role_confidence=conf,
                    )
                )

        for node in nodes:
            txt = node.text
            for m_rel in self.RELATIVE_DATE_RE.finditer(txt):
                raw_expr = m_rel.group(1)
                anchor_role = m_rel.group(2).lower()
                days_offset = self._extract_days_offset(raw_expr)
                context_window = txt[max(0, m_rel.start() - 65):min(len(txt), m_rel.end() + 45)]
                role, conf = self._infer_role(context_window)

                derived_iso = None
                if anchor_role in anchor_dates and days_offset is not None:
                    base_dt = datetime.strptime(anchor_dates[anchor_role], "%Y-%m-%d")
                    derived_iso = (base_dt + timedelta(days=days_offset)).strftime("%Y-%m-%d")

                counter += 1
                records.append(
                    DateRecord(
                        date_id=f"DT_{parsed_doc.document_id}_{counter:03d}",
                        document_id=parsed_doc.document_id,
                        case_id=parsed_doc.case_id,
                        iso=derived_iso,
                        raw=raw_expr,
                        role=role,
                        node_id=node.node_id,
                        page=node.page_start,
                        char_start=node.char_start + m_rel.start(),
                        char_end=node.char_start + m_rel.end(),
                        ambiguous=False,
                        derived=True,
                        derivation_rule=f"{anchor_role}_date ({anchor_dates.get(anchor_role, 'unknown')}) + {days_offset} days",
                        role_confidence=conf,
                    )
                )

        return records

    @staticmethod
    def _parse_explicit_date(raw_date: str) -> Optional[str]:
        if DATEPARSER_AVAILABLE:
            dt = dateparser.parse(raw_date)
            if dt:
                return dt.strftime("%Y-%m-%d")
        try:
            return datetime.strptime(raw_date.strip(), "%d %B %Y").strftime("%Y-%m-%d")
        except ValueError:
            return None

    @staticmethod
    def _infer_role(context: str) -> Tuple[str, str]:
        c_low = context.lower()
        for role_key, kw_list in [
            ("notice", ["notice date", "cure notice", "written notice"]),
            ("amendment", ["amendment date", "amended on"]),
            ("breach", ["breach date", "date of breach"]),
            ("termination", ["termination date"]),
            ("expiration", ["expiration date", "expire on", "remain in full force until"]),
            ("execution", ["execution date", "executed on"]),
            ("effective", ["effective date", "effective as of", "commence on"]),
        ]:
            if any(k in c_low for k in kw_list):
                return role_key, "high"
        return "general", "low"

    def _extract_days_offset(self, expr: str) -> Optional[int]:
        m_num = re.search(r"\((\d+)\)|\b(\d+)\b", expr)
        if m_num:
            return int(m_num.group(1) or m_num.group(2))
        for w, val in self.WORD_TO_INT.items():
            if w in expr.lower():
                return val
        return None


# ============================================================================
# COMPONENT 6: TABLE PROCESSING & CELL-PROVENANCE PANDAS ENGINE (PRIORITY 2D)
# ============================================================================

class LegalTableProcessor:
    """
    Component 6 & Priority 2D:
    - Preserves original table structure, row/column identifiers, and cell-level character offsets.
    - Distinguishes raw cell values (`matched_cells` & `original_source_text`) from calculated values
      (`derived_annotations`).
    - Ensures every cited table value can be traced to its original `TableCellProvenance` cell.
    """

    @staticmethod
    def table_to_dataframe(raw_table: RawTable) -> pd.DataFrame:
        return pd.DataFrame(raw_table.rows, columns=raw_table.headers)

    def table_lookup(
        self,
        raw_table: RawTable,
        row_filter_col: Optional[str] = None,
        row_filter_val: Optional[str] = None,
        select_columns: Optional[List[str]] = None,
        aggregation: Optional[str] = None,
        agg_column: Optional[str] = None,
    ) -> Dict[str, Any]:
        df = self.table_to_dataframe(raw_table)
        matched_row_indices = list(range(len(df)))

        if row_filter_col and row_filter_val is not None and row_filter_col in df.columns:
            mask = df[row_filter_col].astype(str).str.lower().str.contains(str(row_filter_val).lower(), regex=False)
            matched_row_indices = [int(i) for i, m in enumerate(mask.tolist()) if m]
            filtered_df = df.iloc[matched_row_indices].copy()
        else:
            filtered_df = df.copy()

        if select_columns:
            valid_cols = [c for c in select_columns if c in filtered_df.columns]
            if valid_cols:
                filtered_df = filtered_df[valid_cols]

        # Collect exact cell-level provenance records for the matched rows
        matched_set = set(matched_row_indices)
        matched_cells = [
            c.to_dict() for c in raw_table.cells
            if c.row_index in matched_set and (not select_columns or c.col_header in select_columns)
        ]

        # Derived calculation is strictly separated into `derived_annotations`
        derived_annotations: Dict[str, Any] = {}
        agg_result = None
        if aggregation and agg_column and agg_column in df.columns:
            target_series = filtered_df[agg_column] if agg_column in filtered_df.columns else df[agg_column]
            cleaned_nums = (
                target_series.astype(str)
                .str.replace(r"[,$%\s]", "", regex=True)
                .apply(pd.to_numeric, errors="coerce")
                .dropna()
            )
            if not cleaned_nums.empty:
                if aggregation == "sum":
                    agg_result = float(cleaned_nums.sum())
                elif aggregation == "mean":
                    agg_result = float(cleaned_nums.mean())
                elif aggregation == "max":
                    agg_result = float(cleaned_nums.max())
                elif aggregation == "min":
                    agg_result = float(cleaned_nums.min())
                elif aggregation == "count":
                    agg_result = int(cleaned_nums.count())

                derived_annotations = {
                    "is_derived_calculation": True,
                    "operation": aggregation,
                    "target_column": agg_column,
                    "calculated_value": agg_result,
                    "source_table_id": raw_table.table_id,
                    "source_row_indices": matched_row_indices,
                    "note": "Derived numerical calculation; NOT a verbatim source quotation.",
                }

        return {
            "table_id": raw_table.table_id,
            "document_id": raw_table.document_id,
            "caption": raw_table.caption,
            "page": raw_table.page,
            "char_start": raw_table.char_start,
            "char_end": raw_table.char_end,
            "matched_rows": filtered_df.to_dict(orient="records"),
            "matched_cells": matched_cells,
            "markdown_view": self.serialize_rows_with_headers(
                raw_table.caption, list(filtered_df.columns), filtered_df.values.tolist()
            ),
            "derived_annotations": derived_annotations,
            "aggregation": aggregation,
            "aggregation_column": agg_column,
            "aggregation_value": agg_result,
            "source_is_raw_table": True,
            "retrieval_aid_only": False,
        }

    @staticmethod
    def serialize_canonical_table_text(caption: str, headers: List[str], rows: List[List[Any]]) -> str:
        """Matches the exact canonical serialization stored in ParsedDocument.full_text."""
        lines = [f"Table: {caption}", " | ".join(str(h) for h in headers)]
        for r in rows:
            lines.append(" | ".join(str(c) for c in r))
        return "\n".join(lines)

    @staticmethod
    def serialize_rows_with_headers(caption: str, headers: List[str], rows: List[List[Any]]) -> str:
        lines = [
            f"Table: {caption}",
            "| " + " | ".join(str(h) for h in headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
        ]
        for r in rows:
            lines.append("| " + " | ".join(str(c) for c in r) + " |")
        return "\n".join(lines)

    @staticmethod
    def generate_retrieval_summary(raw_table: RawTable) -> str:
        col_list = ", ".join(raw_table.headers)
        first_col_entities = ", ".join(str(r[0]) for r in raw_table.rows[:6] if r)
        return (
            f"[RETRIEVAL AID SUMMARY ONLY - NOT AUTHORITATIVE EVIDENCE] "
            f"Table '{raw_table.caption}' on page {raw_table.page} contains {len(raw_table.rows)} rows "
            f"across columns ({col_list}), covering entries including {first_col_entities}."
        )
