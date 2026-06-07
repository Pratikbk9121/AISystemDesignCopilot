"""
Retrieval-quality evaluation harness.

Computes nDCG@k, Recall@k, MRR, Hit@k for the RAG retrieval stage against
``evals/golden_set.json``.

Relevance signal
----------------
Each golden-set query carries a ``topic`` label (e.g. ``"url_shortener"``).
A retrieved chunk is treated as RELEVANT iff its ``file_name`` metadata
starts with that topic — i.e. it came from the matching system-design
markdown doc.

This is a coarse but consistent binary judgment that requires no manual
chunk-level labeling and lets us A/B retrieval-stage changes quantitatively.

Ablation
--------
Pass ``--ablation`` to run four configurations and print a delta table:

    1. Baseline:        dense-only, no rerank, no BGE prefix.
    2. + BGE prefix:    dense-only, no rerank, BGE query prefix on.
    3. + Hybrid:        dense + BM25 sparse + Qdrant RRF, no rerank.
    4. + Cross-encoder: hybrid + bge-reranker-v2-m3.

Numbers come from real retrieval calls against the live in-process Qdrant
store seeded from ``data/system_design_docs/``. No mocks, no random data.

Usage
-----
    python evals/retrieval_quality.py              # current config only
    python evals/retrieval_quality.py --ablation   # all four configs
    python evals/retrieval_quality.py --k 10       # different k for nDCG/Recall
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# Eval harness is corpus-only — no LLM, no Redis, no API gateway needed.
os.environ.setdefault("REDIS_ENABLED", "false")
os.environ.setdefault("API_AUTH_ENABLED", "false")
os.environ.setdefault("DEBUG", "true")
os.environ.setdefault("LLM_PROVIDER", "openai_compatible")
os.environ.setdefault("LLM_BASE_URL", "http://eval-stub")
os.environ.setdefault("LLM_API_KEY", "eval-stub")
os.environ.setdefault("LLM_MODEL", "eval-stub")

from ranx import Qrels, Run, evaluate  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.core.rag.document_processor import DocumentProcessor  # noqa: E402
from app.core.rag.qdrant_store import QdrantVectorStore  # noqa: E402


GOLDEN_PATH = REPO_ROOT / "evals" / "golden_set.json"
DATA_DIR = REPO_ROOT / "data" / "system_design_docs"


@dataclass
class Config:
    """One ablation configuration."""
    name: str
    enable_hybrid: bool
    enable_rerank: bool
    enable_bge_prefix: bool  # actually a query-side toggle; we patch the helper


def load_golden_queries() -> List[dict]:
    """Load in-domain queries from the golden set.

    Out-of-domain queries (``topic == 'out_of_domain'``) are excluded —
    they intentionally have no relevant doc, so nDCG is undefined.
    """
    with open(GOLDEN_PATH) as f:
        data = json.load(f)
    return [q for q in data["queries"] if q.get("topic") and q["topic"] != "out_of_domain"]


def topic_filename_prefix(topic: str) -> str:
    """Map a topic to the markdown filename prefix.

    Most topics are a 1:1 stem match (``"url_shortener"`` →
    ``"url_shortener_system_design.md"``), but the dropbox doc is named
    ``dropbox_file_storage_system_design.md`` so its stem starts with
    ``"dropbox"`` — the startswith check below handles that uniformly.
    """
    return topic


def is_relevant(chunk_filename: str, topic: str) -> bool:
    """Binary relevance: chunk's source doc matches the query's topic."""
    if not chunk_filename:
        return False
    return chunk_filename.startswith(topic_filename_prefix(topic))


async def seed_store(enable_hybrid: bool) -> QdrantVectorStore:
    """Build a fresh in-memory Qdrant + ingest the markdown corpus."""
    store = QdrantVectorStore(use_memory=True, enable_hybrid=enable_hybrid)
    dp = DocumentProcessor()
    docs = dp.load_documents_from_directory(str(DATA_DIR))
    await store.add_documents(docs)
    return store


def patch_bge_prefix(on: bool) -> None:
    """Force-enable or force-disable the BGE query-side prefix at runtime.

    The real helper lives in ``app.core.rag.embeddings`` and is called
    by ``EmbeddingGenerator._maybe_prefix_query``. We stash the original
    on first call so subsequent ``on=True`` invocations restore it.
    """
    from app.core.rag import embeddings as emb

    if not hasattr(emb, "_bge_query_prefix_applies_real"):
        emb._bge_query_prefix_applies_real = emb._bge_query_prefix_applies  # type: ignore[attr-defined]

    if on:
        emb._bge_query_prefix_applies = emb._bge_query_prefix_applies_real  # type: ignore[attr-defined]
    else:
        emb._bge_query_prefix_applies = lambda provider, model_name: False


async def run_retrieval_for_config(
    cfg: Config,
    queries: List[dict],
    k: int,
) -> Tuple[Qrels, Run]:
    """Run retrieval for every query under the given config, return (qrels, run)."""
    patch_bge_prefix(cfg.enable_bge_prefix)

    store = await seed_store(enable_hybrid=cfg.enable_hybrid)

    # ContextRetrieval owns multi-query + reranking + confidence scoring.
    # We instantiate it directly so we can flip rerank without env reloads.
    from app.core.rag.context_retrieval import ContextRetrieval

    cr = ContextRetrieval(
        vector_store=store,
        llm_client=None,
        use_multi_query=False,           # keep retrieval signal pure for IR metrics
        use_llm_expansion=False,
        enable_reranking=cfg.enable_rerank,
        enable_hallucination_guard=False,  # don't refuse — we want raw rankings
    )

    qrels: Dict[str, Dict[str, int]] = {}
    run: Dict[str, Dict[str, float]] = {}

    for q in queries:
        qid = q["id"]
        topic = q["topic"]
        query_text = q["query"]

        result = await cr.retrieve(query_text)

        # ContextRetrieval returns content strings already trimmed to top-5
        # via the reranker. For IR metrics we need access to the doc
        # metadata (filename) of each ranked chunk — so we duplicate the
        # raw search here for ranking *identity*, then trust the reranker
        # ordering when enabled.
        if cfg.enable_rerank:
            # When rerank is on, ContextRetrieval already invoked the
            # cross-encoder; we re-run the search + rerank inline to
            # capture ranked Document objects with metadata.
            raw = await store.search(query_text, top_k=settings.top_k_retrieval)
            ranked = await cr.reranker.rerank(query=query_text, documents=raw, top_k=k, use_diversity=False)
        else:
            ranked = await store.search(query_text, top_k=k)
            ranked = ranked[:k]

        # Build qrels (ground truth) — relevant doc IDs for this query.
        # ranx wants every relevant id to appear in qrels even if it never
        # was retrieved, so we synthesize stable ids per (filename, rank).
        run_scores: Dict[str, float] = {}
        relevant_ids: Dict[str, int] = {}
        for rank, (doc, score) in enumerate(ranked):
            fname = doc.metadata.get("file_name", "?")
            chunk_idx = doc.metadata.get("chunk_index", rank)
            doc_id = f"{fname}::{chunk_idx}"
            run_scores[doc_id] = float(score) if score is not None else 1.0 / (rank + 1)
            if is_relevant(fname, topic):
                relevant_ids[doc_id] = 1

        # If none of the top-k were relevant, ranx still needs at least one
        # entry in qrels[qid] to score the query — synthesize a sentinel
        # relevant id that the run does NOT contain, so the query
        # correctly scores 0.0 on nDCG/Recall/MRR/Hit.
        if not relevant_ids:
            relevant_ids[f"__missing__{topic}"] = 1

        qrels[qid] = relevant_ids
        run[qid] = run_scores

    close = getattr(store, "close", None)
    if close is not None:
        # close() is sync on the current store implementation.
        try:
            close()
        except Exception:
            pass

    return Qrels(qrels), Run(run)


def format_score(name: str, value: float) -> str:
    return f"{name:<14} {value:6.4f}"


def evaluate_config(qrels: Qrels, run: Run, k: int) -> Dict[str, float]:
    metric_names = [f"ndcg@{k}", f"recall@{k}", f"hit_rate@{k}", "mrr"]
    return {m: float(evaluate(qrels, run, m)) for m in metric_names}


def print_table(
    rows: List[Tuple[str, Dict[str, float]]],
    k: int,
    baseline_name: str | None = None,
) -> None:
    cols = [f"ndcg@{k}", f"recall@{k}", f"hit_rate@{k}", "mrr"]
    name_w = max(len(r[0]) for r in rows) + 2
    header = f"{'Config':<{name_w}}" + "".join(f"{c:>14}" for c in cols)
    if baseline_name:
        header += "      Δ-ndcg"
    print(header)
    print("-" * len(header))

    baseline_ndcg = None
    for name, scores in rows:
        if name == baseline_name:
            baseline_ndcg = scores[f"ndcg@{k}"]
        line = f"{name:<{name_w}}" + "".join(f"{scores[c]:>14.4f}" for c in cols)
        if baseline_name and baseline_ndcg is not None:
            delta = scores[f"ndcg@{k}"] - baseline_ndcg
            sign = "+" if delta >= 0 else ""
            line += f"   {sign}{delta:.4f}"
        print(line)


async def main_async(args: argparse.Namespace) -> None:
    queries = load_golden_queries()
    print(f"# Retrieval-quality eval — {len(queries)} in-domain queries, k={args.k}\n")

    if args.ablation:
        configs = [
            Config("baseline (dense-only, no prefix, no rerank)", enable_hybrid=False, enable_rerank=False, enable_bge_prefix=False),
            Config("+ BGE query prefix",                          enable_hybrid=False, enable_rerank=False, enable_bge_prefix=True),
            Config("+ hybrid (BM25 + dense + RRF)",               enable_hybrid=True,  enable_rerank=False, enable_bge_prefix=True),
            Config("+ cross-encoder rerank (full stack)",         enable_hybrid=True,  enable_rerank=True,  enable_bge_prefix=True),
        ]
    else:
        configs = [
            Config(
                "current config",
                enable_hybrid=settings.enable_hybrid_retrieval,
                enable_rerank=settings.enable_cross_encoder_rerank,
                enable_bge_prefix=True,
            )
        ]

    rows: List[Tuple[str, Dict[str, float]]] = []
    for cfg in configs:
        print(f"Running: {cfg.name} ...", flush=True)
        qrels, run = await run_retrieval_for_config(cfg, queries, args.k)
        scores = evaluate_config(qrels, run, args.k)
        rows.append((cfg.name, scores))

    print()
    print_table(
        rows,
        args.k,
        baseline_name=configs[0].name if args.ablation else None,
    )


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--k", type=int, default=5, help="Top-k for nDCG/Recall/Hit (default 5)")
    p.add_argument("--ablation", action="store_true", help="Run all four ablation configs and print deltas")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(main_async(parse_args()))
