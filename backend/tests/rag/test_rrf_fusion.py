from cicero.rag.retrieval import reciprocal_rank_fusion


def _h(cid: str, score: float) -> dict:
    return {"chunk_id": cid, "score": score, "payload": {"chunk_id": cid}}


def test_rrf_merges_duplicates_and_ranks_shared_hit_first() -> None:
    fused = reciprocal_rank_fusion([_h("A", 0.9), _h("B", 0.8)], [_h("B", 0.5), _h("C", 0.4)])
    ids = [f["chunk_id"] for f in fused]
    assert ids[0] == "B"
    assert ids.count("B") == 1
    assert set(ids) == {"A", "B", "C"}
    b = fused[0]
    assert b["dense_rank"] == 2
    assert b["lexical_rank"] == 1
    assert abs(b["rrf_score"] - (1.0 / 62 + 1.0 / 61)) < 2e-6
    assert b["score"] == b["rrf_score"]


def test_rrf_single_channel() -> None:
    fused = reciprocal_rank_fusion([_h("A", 0.9)], [])
    assert len(fused) == 1
    assert fused[0]["dense_rank"] == 1
    assert fused[0]["lexical_rank"] is None
    assert fused[0]["rrf_score"] == round(1.0 / 61, 6)


def test_rrf_empty() -> None:
    assert reciprocal_rank_fusion([], []) == []
