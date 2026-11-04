from cicero.rag.argon.schemas import EvidenceItem
from cicero.rag.retrieval import pack_context


def _item(node: str, text: str, why: str = "matched", start: int = 0) -> EvidenceItem:
    return EvidenceItem(
        evidence_id="",
        document_id="DOC_1",
        case_id="CASE_1",
        org_id="ORG_1",
        node_id=node,
        page=1,
        char_start=start,
        char_end=start + len(text),
        original_source_text=text,
        extracted_text=text,
        why_included=why,
        token_count=0,
    )


def test_pack_assigns_ids_in_priority_order() -> None:
    matched = [_item("N1", "alpha beta gamma")]
    definitions = [_item("N2", "delta", why="definition", start=50)]
    packed, stats = pack_context(matched, definitions, [], [], [], token_budget=100)
    assert [p.evidence_id for p in packed] == ["EV_001", "EV_002"]
    assert [p.node_id for p in packed] == ["N1", "N2"]
    assert stats["items_packed"] == 2
    assert stats["items_dropped_for_budget"] == 0


def test_pack_drops_over_budget_and_counts() -> None:
    big = _item("N1", " ".join(["word"] * 50))
    packed, stats = pack_context([big], [], [], [], [], token_budget=10)
    assert packed == []
    assert stats["items_dropped_for_budget"] == 1


def test_pack_deduplicates_same_span() -> None:
    a = _item("N1", "alpha beta")
    b = _item("N1", "alpha beta")
    packed, _ = pack_context([a, b], [], [], [], [], token_budget=100)
    assert len(packed) == 1
