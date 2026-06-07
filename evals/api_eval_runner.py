"""
Live API eval runner for the System Design Copilot.

Hits the running backend at ``$BASE_URL/api/v1/system-design/query`` (blocking
JSON endpoint) with a fixed 8-query test matrix that spans the UX spectrum
(in-corpus, near-corpus, out-of-corpus, far-out-of-corpus). For each
successful generation it asks the LLM-as-judge (``evals.judge.judge_response``)
to score the response on the four rubric dimensions.

Run directly:

    python evals/api_eval_runner.py

The script writes a Markdown report to ``evals/results/api_eval_<ts>.md`` and
also prints it to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

# Make ``app.*`` importable when run as ``python evals/api_eval_runner.py``.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.core.config import settings  # noqa: E402  (after sys.path tweak)

# ----------------------------------------------------------------------------
# Test matrix — fixed by spec. DO NOT modify.
# ----------------------------------------------------------------------------

TEST_QUERIES: List[Dict[str, Any]] = [
    {
        "id": "q1-url-shortener",
        "query": "Design a URL shortener like bit.ly",
        "bucket": "in-corpus",
        "judge": True,
    },
    {
        "id": "q2-twitter-feed",
        "query": "Design Twitter's news feed with fan-out vs fan-in",
        "bucket": "in-corpus",
        "judge": True,
    },
    {
        "id": "q3-whatsapp-e2ee",
        "query": "Design WhatsApp end-to-end encrypted messaging",
        "bucket": "in-corpus",
        "judge": True,
    },
    {
        "id": "q4-instagram",
        "query": "Design Instagram with stories and reels",
        "bucket": "in-corpus",
        "judge": True,
    },
    {
        "id": "q5-pinterest",
        "query": "Design Pinterest with boards and image discovery",
        "bucket": "near-corpus",
        "judge": True,
    },
    {
        "id": "q6-discord",
        "query": "Design Discord with channels and voice rooms",
        "bucket": "near-corpus",
        "judge": True,
    },
    {
        "id": "q7-stock-exchange",
        "query": "Design a stock exchange order matching engine",
        "bucket": "out-of-corpus",
        # Save tokens — only judge in-corpus + near-corpus per spec.
        "judge": False,
    },
    {
        "id": "q8-submarine-sonar",
        "query": "Design an underwater submarine sonar telemetry pipeline",
        "bucket": "far-out-of-corpus",
        "judge": False,
    },
]

REQUEST_TIMEOUT_S = 90.0
MAX_CONCURRENCY = 2  # Cap to keep Groq free-tier happy.


# ----------------------------------------------------------------------------
# API call
# ----------------------------------------------------------------------------

async def call_api(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
) -> Dict[str, Any]:
    """POST to the blocking query endpoint and return ``{"ok", ...}`` shape."""
    url = f"{base_url.rstrip('/')}/api/v1/system-design/query"
    payload = {"query": query, "include_evaluation": False}
    t0 = time.perf_counter()
    try:
        resp = await client.post(url, json=payload, timeout=REQUEST_TIMEOUT_S)
    except (httpx.TimeoutException, httpx.HTTPError) as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "body": None,
        }
    latency_ms = int((time.perf_counter() - t0) * 1000)
    if resp.status_code != 200:
        return {
            "ok": False,
            "error": f"HTTP {resp.status_code}: {resp.text[:300]}",
            "latency_ms": latency_ms,
            "body": None,
        }
    try:
        body = resp.json()
    except json.JSONDecodeError as exc:
        return {
            "ok": False,
            "error": f"JSONDecodeError: {exc}",
            "latency_ms": latency_ms,
            "body": None,
        }
    return {"ok": True, "error": None, "latency_ms": latency_ms, "body": body}


# ----------------------------------------------------------------------------
# Judge (lazy import so the script still runs if the judge stack is broken)
# ----------------------------------------------------------------------------

async def maybe_judge(
    case: Dict[str, Any],
    response_body: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """
    Score a single response with the LLM judge. Returns ``None`` if judging
    was skipped or the judge failed. We catch *all* exceptions because we
    never want the judge to break the API metric run.
    """
    if not case.get("judge"):
        return None
    # If the generator refused outright, there's no architecture to score.
    if response_body.get("insufficient_knowledge") and not response_body.get("architecture"):
        return None
    try:
        from app.core.llm.client import LLMClient
        from evals.judge import judge_response

        llm = LLMClient()
        # Expectations payload follows the same shape used by the existing
        # golden-set runs in evals/judge.py.
        expectations = {
            "expects_tool_call": False,
            "expects_guard_trigger": case.get("bucket") in {"out-of-corpus", "far-out-of-corpus"},
            "topic": case.get("bucket"),
        }
        score = await judge_response(
            llm=llm,
            query_id=case["id"],
            query=case["query"],
            response_payload=response_body,
            expectations=expectations,
        )
        return score.to_dict()
    except Exception as exc:  # pragma: no cover — defensive
        return {"error": f"{type(exc).__name__}: {exc}"}


# ----------------------------------------------------------------------------
# Single case orchestration
# ----------------------------------------------------------------------------

async def run_case(
    sem: asyncio.Semaphore,
    client: httpx.AsyncClient,
    base_url: str,
    case: Dict[str, Any],
) -> Dict[str, Any]:
    async with sem:
        api = await call_api(client, base_url, case["query"])

    record: Dict[str, Any] = {
        "id": case["id"],
        "query": case["query"],
        "bucket": case["bucket"],
        "ok": api["ok"],
        "error": api["error"],
        "latency_ms": api["latency_ms"],
        "judge": None,
    }

    if not api["ok"]:
        return record

    body = api["body"]
    conf = (body.get("confidence_metrics") or {}).get("overall_confidence")
    tokens = (body.get("token_usage") or {}).get("total_tokens", 0)

    record.update({
        "confidence": conf,
        "confidence_level": (body.get("confidence_metrics") or {}).get("confidence_level"),
        "degraded_mode": bool(body.get("degraded_mode")),
        "insufficient_knowledge": bool(body.get("insufficient_knowledge")),
        "related_patterns": body.get("related_patterns") or [],
        "tokens": tokens,
        "revision_count": body.get("revision_count", 0),
        "num_services": len((body.get("architecture") or {}).get("services") or []),
        "num_tradeoffs": len((body.get("architecture") or {}).get("tradeoffs") or []),
    })

    record["judge"] = await maybe_judge(case, body)
    return record


# ----------------------------------------------------------------------------
# Report rendering
# ----------------------------------------------------------------------------

def _fmt_num(x: Any, places: int = 2) -> str:
    if x is None:
        return "-"
    if isinstance(x, float):
        return f"{x:.{places}f}"
    return str(x)


def _row(r: Dict[str, Any], idx: int) -> str:
    if not r["ok"]:
        return (
            f"| {idx} | {r['query']} | err | - | - | {r['latency_ms']} | - "
            f"| - | - | - | - | - |"
        )
    j = r.get("judge") or {}
    has_scores = isinstance(j, dict) and "completeness" in j
    return (
        f"| {idx} | {r['query']} "
        f"| {_fmt_num(r.get('confidence'))} "
        f"| {'yes' if r.get('degraded_mode') else 'no'} "
        f"| {'yes' if r.get('insufficient_knowledge') else 'no'} "
        f"| {r['latency_ms']} "
        f"| {r.get('tokens', 0)} "
        f"| {_fmt_num(j.get('completeness')) if has_scores else '-'} "
        f"| {_fmt_num(j.get('scalability_reasoning')) if has_scores else '-'} "
        f"| {_fmt_num(j.get('tradeoff_coverage')) if has_scores else '-'} "
        f"| {_fmt_num(j.get('factuality')) if has_scores else '-'} "
        f"| {_fmt_num(j.get('overall')) if has_scores else '-'} |"
    )


def _agg(vals: List[float]) -> Dict[str, float]:
    if not vals:
        return {"mean": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    return {
        "mean": round(statistics.fmean(vals), 2),
        "median": round(statistics.median(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
    }


def render_report(
    results: List[Dict[str, Any]],
    base_url: str,
    timestamp: str,
) -> str:
    lines: List[str] = []
    lines.append(f"# Live API Eval — {timestamp}")
    lines.append("")
    lines.append(
        f"Backend: {base_url} | LLM: {settings.effective_llm_model} "
        f"| Rerank: {'on' if settings.enable_cross_encoder_rerank else 'off'} "
        f"| Threshold: {settings.confidence_threshold}"
    )
    lines.append("")
    lines.append("## Per-query results")
    lines.append("")
    lines.append(
        "| # | Query | Conf | Degraded | Insuff | Lat(ms) | Tok "
        "| Compl | Scal | Trade | Fact | Mean |"
    )
    lines.append(
        "|---|-------|-----:|:--------:|:------:|--------:|----:|------:|-----:|------:|-----:|-----:|"
    )
    for i, r in enumerate(results, start=1):
        lines.append(_row(r, i))
    lines.append("")

    ok_results = [r for r in results if r["ok"]]
    judged = [
        r for r in ok_results
        if isinstance(r.get("judge"), dict) and "completeness" in r["judge"]
    ]
    degraded = sum(1 for r in ok_results if r.get("degraded_mode"))
    insuff = sum(1 for r in ok_results if r.get("insufficient_knowledge"))
    confs = [r["confidence"] for r in ok_results if isinstance(r.get("confidence"), (int, float))]
    lats = [r["latency_ms"] for r in results]
    toks = [r.get("tokens", 0) for r in ok_results]

    dims = ["completeness", "scalability_reasoning", "tradeoff_coverage", "factuality"]
    dim_aggs = {d: _agg([float(r["judge"][d]) for r in judged]) for d in dims}
    overall_mean = (
        round(statistics.fmean([float(r["judge"]["overall"]) for r in judged]), 2)
        if judged
        else None
    )

    lines.append("## Aggregate")
    lines.append("")
    lines.append(f"- Queries run: {len(results)}")
    lines.append(f"- Successful generations: {len(ok_results)}")
    lines.append(f"- Degraded mode: {degraded}")
    lines.append(f"- Insufficient knowledge: {insuff}")
    lines.append(f"- Judged queries: {len(judged)}")
    lines.append(
        f"- Mean confidence: {_fmt_num(statistics.fmean(confs)) if confs else '-'}"
    )
    lines.append(
        f"- Latency ms — mean: {int(statistics.fmean(lats))}, "
        f"median: {int(statistics.median(lats))}, "
        f"min: {min(lats)}, max: {max(lats)}"
    )
    if overall_mean is not None:
        lines.append(f"- Mean judge score (4-dim mean of means): {overall_mean}")
    else:
        lines.append("- Mean judge score: judge unavailable or no judged queries")
    lines.append(f"- Total tokens: {sum(toks)}")
    lines.append("")
    lines.append("### Per-dimension judge stats")
    lines.append("")
    lines.append("| Dimension | mean | median | min | max |")
    lines.append("|-----------|-----:|-------:|----:|----:|")
    for d in dims:
        a = dim_aggs[d]
        lines.append(f"| {d} | {a['mean']} | {a['median']} | {a['min']} | {a['max']} |")
    lines.append("")

    # Per-query critique (only judged queries that have one_line_critique)
    critiques = [
        (r["id"], r["judge"].get("one_line_critique"))
        for r in judged
        if r["judge"].get("one_line_critique")
    ]
    if critiques:
        lines.append("## Per-query judge critiques")
        lines.append("")
        for qid, crit in critiques:
            lines.append(f"- **{qid}**: {crit}")
        lines.append("")

    # Headline finding — generated from aggregate numbers, not synthesized.
    pct_degraded = (degraded / len(ok_results) * 100) if ok_results else 0.0
    if overall_mean is None:
        headline = (
            f"Backend served {len(ok_results)}/{len(results)} queries "
            f"({pct_degraded:.0f}% degraded, {insuff} refused); judge unavailable."
        )
    else:
        headline = (
            f"Backend served {len(ok_results)}/{len(results)} queries with mean judge "
            f"score {overall_mean}/10 across {len(judged)} judged designs; "
            f"{pct_degraded:.0f}% triggered degraded mode and {insuff} hit "
            f"insufficient-knowledge refusal."
        )
    lines.append("## Headline finding")
    lines.append("")
    lines.append(headline)
    lines.append("")

    return "\n".join(lines)


# ----------------------------------------------------------------------------
# Entrypoint
# ----------------------------------------------------------------------------

async def main_async(base_url: str) -> int:
    sem = asyncio.Semaphore(MAX_CONCURRENCY)
    async with httpx.AsyncClient() as client:
        tasks = [run_case(sem, client, base_url, c) for c in TEST_QUERIES]
        results = await asyncio.gather(*tasks)

    # Preserve test-matrix ordering (asyncio.gather already does).
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")
    report = render_report(results, base_url, timestamp)

    results_dir = Path(__file__).resolve().parent / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    out_md = results_dir / f"api_eval_{timestamp}.md"
    out_md.write_text(report, encoding="utf-8")

    # Also dump raw JSON next to the markdown for downstream analysis.
    out_json = results_dir / f"api_eval_{timestamp}.json"
    out_json.write_text(
        json.dumps({"timestamp": timestamp, "base_url": base_url, "results": results}, indent=2, default=str),
        encoding="utf-8",
    )

    print(report)
    print(f"\n[runner] wrote {out_md}")
    print(f"[runner] wrote {out_json}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Live API eval runner")
    parser.add_argument(
        "--base-url",
        default=os.environ.get("EVAL_BASE_URL", "http://localhost:8000"),
        help="Backend base URL (default: http://localhost:8000).",
    )
    args = parser.parse_args()
    return asyncio.run(main_async(args.base_url))


if __name__ == "__main__":
    raise SystemExit(main())
