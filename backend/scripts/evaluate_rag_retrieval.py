"""Evaluate case-scoped RAG retrieval against a JSONL gold set.

Each JSONL row: {"organization_id": "...", "case_id": "...", "query": "...",
                 "relevant_document_ids": ["..."], "top_k": 8}
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx


async def main(path: Path) -> None:
    base_url = os.environ["CICERO_RAG_WORKER_URL"].rstrip("/")
    token = os.environ["CICERO_RAG_SERVICE_TOKEN"]
    total = 0
    variants = {
        "full": {},
        "dense_only": {"dense": True, "lexical": False, "exact": False, "reranker": False},
        "lexical_only": {"dense": False, "lexical": True, "exact": False, "reranker": False},
        "hybrid_no_exact": {"dense": True, "lexical": True, "exact": False, "reranker": True},
        "hybrid_no_reranker": {"dense": True, "lexical": True, "exact": True, "reranker": False},
    }
    metrics = {
        name: {
            "queries": 0,
            "recall_at_k": 0.0,
            "hit_rate_at_k": 0.0,
            "mrr": 0.0,
        }
        for name in variants
    }
    async with httpx.AsyncClient(timeout=120.0) as client:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            relevant = set(item["relevant_document_ids"])
            if not relevant:
                continue
            total += 1
            for name, ablation in variants.items():
                request_body = {
                    key: item[key]
                    for key in ("organization_id", "case_id", "query", "top_k")
                    if key in item
                }
                if ablation:
                    request_body["ablation"] = ablation
                response = await client.post(
                    f"{base_url}/retrieve",
                    headers={"Authorization": f"Bearer {token}"},
                    json=request_body,
                )
                response.raise_for_status()
                evidence = response.json()["evidence"]
                ranks = [
                    idx
                    for idx, hit in enumerate(evidence, start=1)
                    if hit["document_id"] in relevant
                ]
                metrics[name]["queries"] += 1
                retrieved = {hit["document_id"] for hit in evidence}
                metrics[name]["recall_at_k"] += len(retrieved & relevant) / len(relevant)
                metrics[name]["hit_rate_at_k"] += float(bool(ranks))
                metrics[name]["mrr"] += 1.0 / min(ranks) if ranks else 0.0
    if not total:
        raise SystemExit("Gold set is empty")
    for values in metrics.values():
        count = values["queries"]
        if count:
            for key in ("recall_at_k", "hit_rate_at_k", "mrr"):
                values[key] /= count
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/evaluate_rag_retrieval.py gold_queries.jsonl")
    asyncio.run(main(Path(sys.argv[1])))
