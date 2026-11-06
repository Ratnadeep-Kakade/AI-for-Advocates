"""
Module 6: Components 8 and 12 — BGE-M3 Dense Embedder & BGE Reranker v2-M3 (PostgreSQL + pgvector Edition)
Updated for PostgreSQL + pgvector Migration:
1. `BGEM3Embedder` generates 1024-dimensional normalized dense vectors (`return_dense=True, return_sparse=False`)
   and strictly validates that the output tensor dimension equals `self.dense_dim` (1024) before returning.
2. Replaces Qdrant's sparse vector generation with PostgreSQL Full-Text Search (`tsvector` + GIN + `ts_rank_cd`)
   and exact legal identifier array indexing in `PostgresLegalStore` (`argon_rag/postgres_store.py`).
   NOTE: PostgreSQL Full-Text Search is deterministic lexical/statistical matching and is NOT equivalent
   to BGE-M3's learned neural sparse representations.
3. Retains strict no-silent-fallback enforcement (`simulation_mode=False` by default raises `RuntimeError`
   if `FlagEmbedding` / `BAAI/bge-m3` / `BAAI/bge-reranker-v2-m3` cannot initialize).
"""

import re
import math
import hashlib
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
import numpy as np


try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

try:
    from FlagEmbedding import BGEM3FlagModel, FlagReranker
    FLAG_EMBEDDING_AVAILABLE = True
except ImportError:
    FLAG_EMBEDDING_AVAILABLE = False


# ============================================================================
# COMPONENT 8: BGE-M3 DENSE EMBEDDER (WITH DIMENSION VALIDATION)
# ============================================================================

class EmbedderInterface(ABC):
    @property
    @abstractmethod
    def model_version(self) -> str:
        pass

    @property
    @abstractmethod
    def is_simulation_mode(self) -> bool:
        pass

    @property
    @abstractmethod
    def init_status(self) -> str:
        pass

    @property
    @abstractmethod
    def dense_dim(self) -> int:
        pass

    @abstractmethod
    def encode_batch(self, texts: List[str], batch_size: int = 16) -> Dict[str, Any]:
        pass


class BGEM3Embedder(EmbedderInterface):
    """
    Production & Colab BGE-M3 Dense Embedder (`BAAI/bge-m3`) for `pgvector`.
    - Validates that output embedding dimension strictly matches `self.dense_dim` (1024).
    - Raises `RuntimeError` when `simulation_mode=False` (default) and `FlagEmbedding` or
      `BAAI/bge-m3` fails to load.
    """

    STOPWORDS = {
        "the", "and", "of", "to", "in", "a", "for", "is", "on", "that", "by", "this", "with",
        "as", "be", "are", "or", "an", "at", "from", "under", "shall", "any", "such", "which",
        "what", "where", "when", "how", "who", "does", "do", "clause", "section", "article",
        "agreement", "agreements", "contract", "contracts", "provision", "provisions", "these", "two",
    }

    def __init__(
        self,
        model_name: str = "BAAI/bge-m3",
        device: Optional[str] = None,
        max_length: int = 2048,
        expected_dim: int = 1024,
        simulation_mode: bool = False,
    ):
        self.model_name = model_name
        self.max_length = max_length
        self._dense_dim = int(expected_dim)
        self._simulation_mode = bool(simulation_mode)
        self.model = None

        if device is None:
            if TORCH_AVAILABLE and torch.cuda.is_available():
                self.device = "cuda"
                self.use_fp16 = True
            else:
                self.device = "cpu"
                self.use_fp16 = False
        else:
            self.device = device
            self.use_fp16 = (device == "cuda")

        if self._simulation_mode:
            self._version = "SIMULATION_ONLY_NGRAM_HASH_EMBEDDER (NOT BGE-M3)"
            self._init_status = "SIMULATION_MODE_EXPLICITLY_ENABLED"
            return

        if not FLAG_EMBEDDING_AVAILABLE:
            raise RuntimeError(
                f"CRITICAL MODEL INITIALIZATION FAILURE: Cannot initialize '{self.model_name}' because "
                "'FlagEmbedding' is not installed in the current Python environment. "
                "Install it via `pip install FlagEmbedding` in Google Colab, or explicitly pass "
                "`simulation_mode=True` ONLY if running offline structural unit tests."
            )

        try:
            self.model = BGEM3FlagModel(
                self.model_name,
                use_fp16=self.use_fp16,
                device=self.device,
            )
            # Validate output dimension immediately upon initialization with a probe sentence
            probe = self.model.encode(
                ["Dimension validation probe"],
                batch_size=1,
                max_length=32,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            probe_vecs = np.asarray(probe["dense_vecs"], dtype=np.float32)
            if probe_vecs.ndim != 2 or probe_vecs.shape[1] != self._dense_dim:
                raise ValueError(
                    f"Model '{self.model_name}' produced dense dimension {probe_vecs.shape}, "
                    f"which does not match expected pgvector column dimension {self._dense_dim}."
                )
            self._version = f"{self.model_name} (FlagEmbedding dense={self._dense_dim}d, device={self.device}, fp16={self.use_fp16})"
            self._init_status = "REAL_MODEL_INITIALIZED_AND_DIM_VERIFIED"
        except Exception as e:
            raise RuntimeError(
                f"CRITICAL MODEL INITIALIZATION FAILURE: Failed to load or validate '{self.model_name}' on device='{self.device}'. "
                f"Underlying error: {type(e).__name__}: {e}. "
                "Silent fallback is disabled to prevent misleading evaluation results."
            ) from e

    @property
    def model_version(self) -> str:
        return self._version

    @property
    def is_simulation_mode(self) -> bool:
        return self._simulation_mode

    @property
    def init_status(self) -> str:
        return self._init_status

    @property
    def dense_dim(self) -> int:
        return self._dense_dim

    def validate_output_dimensions(self, dense_vecs: np.ndarray, expected_rows: int) -> None:
        if dense_vecs.ndim != 2 or dense_vecs.shape[0] != expected_rows or dense_vecs.shape[1] != self._dense_dim:
            raise ValueError(
                f"Embedding dimension validation failed: expected shape ({expected_rows}, {self._dense_dim}), "
                f"got {dense_vecs.shape}."
            )

    def encode_batch(self, texts: List[str], batch_size: int = 16) -> Dict[str, Any]:
        if not texts:
            return {"dense_vecs": np.zeros((0, self._dense_dim), dtype=np.float32)}

        if not self._simulation_mode:
            if self.model is None:
                raise RuntimeError("BGEM3Embedder model is uninitialized.")
            output = self.model.encode(
                texts,
                batch_size=batch_size,
                max_length=self.max_length,
                return_dense=True,
                return_sparse=False,
                return_colbert_vecs=False,
            )
            dense_vecs = np.asarray(output["dense_vecs"], dtype=np.float32)
            self.validate_output_dimensions(dense_vecs, expected_rows=len(texts))
            norms = np.linalg.norm(dense_vecs, axis=1, keepdims=True)
            dense_vecs = dense_vecs / np.clip(norms, 1e-9, None)
            return {"dense_vecs": dense_vecs}

        dense_vecs = self._encode_neutral_feature_hash(texts)
        self.validate_output_dimensions(dense_vecs, expected_rows=len(texts))
        return {"dense_vecs": dense_vecs}

    def _encode_neutral_feature_hash(self, texts: List[str]) -> np.ndarray:
        dense_mat = np.zeros((len(texts), self._dense_dim), dtype=np.float32)
        for row_idx, txt in enumerate(texts):
            content_part = txt.split("Content:\n")[-1] if "Content:\n" in txt else txt
            tokens = re.findall(r"[a-zA-Z0-9_\-\.]+", content_part.lower())

            tf_counts: Dict[str, int] = {}
            for tok in tokens:
                if len(tok) > 1 and tok not in self.STOPWORDS:
                    tf_counts[tok] = tf_counts.get(tok, 0) + 1

            vec = np.zeros(self._dense_dim, dtype=np.float32)
            for tok, cnt in tf_counts.items():
                w = 1.0 + math.log(cnt)
                features = [tok]
                if len(tok) >= 5:
                    features.append(f"stem:{tok[:5]}")
                for i in range(max(0, len(tok) - 3)):
                    features.append(f"cg:{tok[i:i+4]}")
                for feat in features:
                    h = int(hashlib.md5(feat.encode("utf-8")).hexdigest()[:8], 16)
                    dim = h % self._dense_dim
                    sign = 1.0 if ((h >> 16) & 1) == 0 else -1.0
                    vec[dim] += sign * w

            norm = np.linalg.norm(vec)
            if norm > 1e-9:
                vec = vec / norm
            dense_mat[row_idx] = vec
        return dense_mat


# ============================================================================
# COMPONENT 12: CROSS-ENCODER RERANKER (NO SILENT FALLBACKS)
# ============================================================================

class CrossEncoderReranker:
    """
    Component 12: Cross-encoder reranker using `BAAI/bge-reranker-v2-m3` via FlagReranker.
    """

    def __init__(
        self,
        model_name: str = "BAAI/bge-reranker-v2-m3",
        device: Optional[str] = None,
        rejection_threshold: float = 0.22,
        simulation_mode: bool = False,
    ):
        self.model_name = model_name
        self.rejection_threshold = float(rejection_threshold)
        self._simulation_mode = bool(simulation_mode)
        self.reranker = None

        if device is None:
            if TORCH_AVAILABLE and torch.cuda.is_available():
                self.device = "cuda"
                self.use_fp16 = True
            else:
                self.device = "cpu"
                self.use_fp16 = False
        else:
            self.device = device
            self.use_fp16 = (device == "cuda")

        if self._simulation_mode:
            self._version = "SIMULATION_ONLY_TOKEN_OVERLAP_RERANKER (NOT BGE-RERANKER)"
            self._init_status = "SIMULATION_MODE_EXPLICITLY_ENABLED"
            return

        if not FLAG_EMBEDDING_AVAILABLE:
            raise RuntimeError(
                f"CRITICAL RERANKER INITIALIZATION FAILURE: Cannot initialize '{self.model_name}' because "
                "'FlagEmbedding' is not installed in the current Python environment. "
                "Install it via `pip install FlagEmbedding` in Google Colab, or explicitly pass "
                "`simulation_mode=True` ONLY if running offline structural unit tests."
            )

        try:
            self.reranker = FlagReranker(self.model_name, use_fp16=self.use_fp16, device=self.device)
            self._version = f"{self.model_name} (FlagReranker, device={self.device}, fp16={self.use_fp16})"
            self._init_status = "REAL_MODEL_INITIALIZED"
        except Exception as e:
            raise RuntimeError(
                f"CRITICAL RERANKER INITIALIZATION FAILURE: Failed to load '{self.model_name}' on device='{self.device}'. "
                f"Underlying error: {type(e).__name__}: {e}. "
                "Silent fallback is disabled to prevent misleading evaluation results."
            ) from e

    @property
    def model_version(self) -> str:
        return self._version

    @property
    def is_simulation_mode(self) -> bool:
        return self._simulation_mode

    @property
    def init_status(self) -> str:
        return self._init_status

    def rerank(
        self,
        query: str,
        candidates: List[Dict[str, Any]],
        top_k: int = 8,
        threshold_override: Optional[float] = None,
    ) -> Tuple[List[Dict[str, Any]], bool, List[Dict[str, Any]]]:
        if not candidates:
            return [], True, []

        active_threshold = float(threshold_override) if threshold_override is not None else self.rejection_threshold
        pairs = [[query, c["payload"].get("embedding_text", c["payload"].get("clean_text", ""))] for c in candidates]

        if not self._simulation_mode:
            if self.reranker is None:
                raise RuntimeError("CrossEncoderReranker model is uninitialized.")
            raw_scores = self.reranker.compute_score(pairs, normalize=True)
            if isinstance(raw_scores, (float, int)):
                scores = [float(raw_scores)]
            else:
                scores = [float(s) for s in raw_scores]
        else:
            scores = self._compute_neutral_simulation_score(query, candidates)

        reranked = []
        diagnostics = []
        for cand, sc in zip(candidates, scores):
            item = dict(cand)
            item["rerank_score"] = round(sc, 4)
            reranked.append(item)

        reranked.sort(key=lambda x: x["rerank_score"], reverse=True)
        for rank_idx, r in enumerate(reranked):
            passed = r["rerank_score"] >= active_threshold and rank_idx < top_k
            diagnostics.append({
                "chunk_id": r["chunk_id"],
                "clause_label": r["payload"].get("clause_label", ""),
                "rrf_score": r.get("rrf_score", r.get("score", 0.0)),
                "rerank_score": r["rerank_score"],
                "threshold_applied": active_threshold,
                "passed_threshold": passed,
            })

        filtered = [r for r in reranked[:top_k] if r["rerank_score"] >= active_threshold]
        if not filtered:
            return [], True, diagnostics

        return filtered, False, diagnostics

    @staticmethod
    def _compute_neutral_simulation_score(query: str, candidates: List[Dict[str, Any]]) -> List[float]:
        q_tokens = [
            t for t in re.findall(r"[a-zA-Z0-9_\-\.]+", query.lower())
            if t not in BGEM3Embedder.STOPWORDS and len(t) > 1
        ]
        if not q_tokens:
            return [0.0 for _ in candidates]

        q_stems = {t[:5] if len(t) >= 5 else t for t in q_tokens}
        scores: List[float] = []

        for cand in candidates:
            pl = cand["payload"]
            emb_txt = pl.get("embedding_text", "").lower()
            c_tokens = [
                t for t in re.findall(r"[a-zA-Z0-9_\-\.]+", emb_txt)
                if t not in BGEM3Embedder.STOPWORDS and len(t) > 1
            ]
            c_set = set(c_tokens)
            c_stems = {t[:5] if len(t) >= 5 else t for t in c_tokens}

            exact_hits = sum(1.0 for qt in q_tokens if qt in c_set)
            stem_hits = sum(0.6 for qt in q_tokens if qt not in c_set and (qt[:5] if len(qt) >= 5 else qt) in c_stems)
            coverage = (exact_hits + stem_hits) / max(len(q_tokens), 1)
            rrf_prior = min(0.10, float(cand.get("rrf_score", cand.get("score", 0.0))) * 3.0)
            scores.append(float(min(0.99, round((0.85 * coverage) + (0.05 if exact_hits > 0 else 0.0) + rrf_prior, 4))))

        return scores
