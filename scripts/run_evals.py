#!/usr/bin/env python
"""
Run the golden-set evaluation against a running server.

Usage:
    python scripts/run_evals.py                     # hit local server, full golden set
    python scripts/run_evals.py --limit 5           # smoke test on the first 5 queries
    python scripts/run_evals.py --filter scale-     # only ids matching prefix
    python scripts/run_evals.py --url http://...    # different server
    python scripts/run_evals.py --judge-model gpt-4.1

Writes results to ``evals/results/<timestamp>.json`` and prints a
markdown summary table to stdout.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from app.core.llm.client import LLMClient  # noqa: E402
from evals.judge import judge_response, JudgeScore  # noqa: E402

logger = logging.getLogger("evals.runner")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


GOLDEN_SET_PATH = REPO_ROOT / "evals" / "golden_set.json"
RESULTS_DIR = REPO_ROOT / "evals" / "results"


# ============================================================================
# API call
# ============================================================================

async def call_api(
    client: httpx.AsyncClient,
    base_url: str,
    query: str,
    include_evaluation: bool,
    timeout: float,
) -> Dict[str, Any]:
    """POST a single query and return the parsed response."""
    url = f"{base_url.rstrip('/')}/api/v1/system-design/query"
    payload = {"query": query, "include_evaluation": include_evaluation}
    r = await client.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


# ============================================================================
# Aggregation & rendering
# ============================================================================

def aggregate(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute summary statistics over per-query results."""
    if not results:
        return {}

    n = len(results)
    dims = ["completeness", "scalability_reasoning", "tradeoff_coverage", "factuality"]
    sums = {d: 0 for d in dims}
    overall_sum = 0.0
    tools_when_expected = 0
    tools_when_not_expected = 0
    ood_correct = 0
    ood_total = 0
    in_domain = 0
    in_domain_overall = 0.0

    for row in results:
        score = row["score"]
        for d in dims:
            sums[d] += score[d]
        overall_sum += score["overall"]

        exp = row["expectations"]
        if exp.get("expects_tool_call"):
            if score["tool_used"]:
                tools_when_expected += 1
        else:
            if score["tool_used"]:
                tools_when_not_expected += 1

        if exp.get("expects_guard_trigger"):
            ood_total += 1
            if score["guard_triggered_correctly"]:
                ood_correct += 1
        else:
            in_domain += 1
            in_domain_overall += score["overall"]

    expected_tool_calls = sum(
        1 for r in results if r["expectations"].get("expects_tool_call")
    )
    not_expected_tool_calls = n - expected_tool_calls

    return {
        "n_queries": n,
        "overall_score": round(overall_sum / n, 2),
        "in_domain_score": round(in_domain_overall / in_domain, 2) if in_domain else None,
        "by_dimension": {d: round(sums[d] / n, 2) for d in dims},
        "tool_use": {
            "fired_when_expected": tools_when_expected,
            "expected_count": expected_tool_calls,
            "fired_when_not_expected": tools_when_not_expected,
            "not_expected_count": not_expected_tool_calls,
            "precision": round(
                tools_when_expected / max(tools_when_expected + tools_when_not_expected, 1),
                2,
            ),
            "recall": round(tools_when_expected / max(expected_tool_calls, 1), 2),
        },
        "ood_refusal": {
            "correct": ood_correct,
            "total": ood_total,
            "accuracy": round(ood_correct / ood_total, 2) if ood_total else None,
        },
    }


def render_markdown(results: List[Dict[str, Any]], summary: Dict[str, Any]) -> str:
    """Build a human-friendly markdown report."""
    lines = []
    lines.append("# Eval results\n")
    lines.append(
        f"- **N queries:** {summary['n_queries']}\n"
        f"- **Overall score:** **{summary['overall_score']} / 10**\n"
        f"- **In-domain score:** {summary['in_domain_score']} / 10\n"
    )
    bd = summary["by_dimension"]
    lines.append("## By dimension\n")
    lines.append("| Dimension | Score (/10) |")
    lines.append("|---|---|")
    for d in ["completeness", "scalability_reasoning", "tradeoff_coverage", "factuality"]:
        lines.append(f"| {d} | {bd[d]} |")
    lines.append("")

    tu = summary["tool_use"]
    lines.append("## Tool use")
    lines.append(
        f"- Fired when expected: **{tu['fired_when_expected']} / {tu['expected_count']}** "
        f"(recall = {tu['recall']})"
    )
    lines.append(
        f"- Fired when NOT expected: **{tu['fired_when_not_expected']} / {tu['not_expected_count']}** "
        f"(precision = {tu['precision']})\n"
    )

    if summary["ood_refusal"]["total"]:
        oo = summary["ood_refusal"]
        lines.append("## Out-of-domain refusal")
        lines.append(f"- **{oo['correct']} / {oo['total']}** refused correctly (accuracy = {oo['accuracy']})\n")

    lines.append("## Per-query")
    lines.append("| ID | Overall | Comp | Scale | Trade | Fact | Tool | Critique |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for row in results:
        s = row["score"]
        lines.append(
            "| {id} | {ov} | {c} | {s} | {t} | {f} | {tool} | {crit} |".format(
                id=row["id"],
                ov=s["overall"],
                c=s["completeness"],
                s=s["scalability_reasoning"],
                t=s["tradeoff_coverage"],
                f=s["factuality"],
                tool="✓" if s["tool_used"] else "",
                crit=(s["one_line_critique"] or "").replace("|", "\\|")[:90],
            )
        )
    return "\n".join(lines)


# ============================================================================
# Main
# ============================================================================

async def run_one(
    client: httpx.AsyncClient,
    judge_llm: LLMClient,
    entry: Dict[str, Any],
    base_url: str,
    timeout: float,
) -> Dict[str, Any]:
    """Process a single golden-set entry: API call + judge."""
    qid = entry["id"]
    query = entry["query"]
    expectations = {
        "topic": entry.get("topic"),
        "expects_tool_call": bool(entry.get("expects_tool_call")),
        "expects_guard_trigger": bool(entry.get("expects_guard_trigger")),
    }

    t0 = time.monotonic()
    try:
        api_response = await call_api(
            client, base_url, query, include_evaluation=True, timeout=timeout
        )
        api_error = None
    except Exception as e:  # noqa: BLE001
        logger.exception("[%s] API call failed", qid)
        api_response = {}
        api_error = str(e)

    api_latency_s = round(time.monotonic() - t0, 2)

    if api_error:
        score = JudgeScore(
            completeness=0,
            scalability_reasoning=0,
            tradeoff_coverage=0,
            factuality=0,
            tool_used=False,
            appropriate_tool_use=False,
            guard_triggered_correctly=None,
            one_line_critique=f"API error: {api_error}",
        )
    else:
        score = await judge_response(
            llm=judge_llm,
            query_id=qid,
            query=query,
            response_payload=api_response,
            expectations=expectations,
        )

    logger.info(
        "[%s] overall=%s comp=%d scale=%d trade=%d fact=%d tool=%s latency=%ss",
        qid,
        score.overall,
        score.completeness,
        score.scalability_reasoning,
        score.tradeoff_coverage,
        score.factuality,
        score.tool_used,
        api_latency_s,
    )

    return {
        "id": qid,
        "query": query,
        "expectations": expectations,
        "score": score.to_dict(),
        "api_latency_s": api_latency_s,
        "api_error": api_error,
        "revision_count": api_response.get("revision_count", 0) if not api_error else None,
        "tool_calls": api_response.get("tool_calls") or [] if not api_error else [],
        "token_usage": api_response.get("token_usage") if not api_error else None,
    }


async def main_async(args: argparse.Namespace) -> int:
    golden = json.loads(GOLDEN_SET_PATH.read_text())
    entries = golden["queries"]

    if args.filter:
        entries = [e for e in entries if e["id"].startswith(args.filter)]
    if args.limit:
        entries = entries[: args.limit]

    if not entries:
        logger.error("No golden-set entries matched the filter")
        return 1

    logger.info("Running %d queries against %s", len(entries), args.url)

    judge_llm = LLMClient(model=args.judge_model)

    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=args.timeout) as client:
        # Concurrent fan-out but bounded so we don't melt Bifrost.
        sem = asyncio.Semaphore(args.concurrency)

        async def bounded(entry: Dict[str, Any]):
            async with sem:
                return await run_one(client, judge_llm, entry, args.url, args.timeout)

        tasks = [asyncio.create_task(bounded(e)) for e in entries]
        for fut in asyncio.as_completed(tasks):
            results.append(await fut)

    # Sort by golden-set order for the report.
    order = {e["id"]: i for i, e in enumerate(entries)}
    results.sort(key=lambda r: order.get(r["id"], 1_000_000))

    summary = aggregate(results)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    label = f"_{args.label}" if args.label else ""
    out_path = RESULTS_DIR / f"{ts}{label}.json"

    out_path.write_text(
        json.dumps(
            {
                "timestamp": ts,
                "config": {
                    "url": args.url,
                    "judge_model": args.judge_model,
                    "n_queries": len(entries),
                    "label": args.label,
                },
                "summary": summary,
                "results": results,
            },
            indent=2,
            default=str,
        )
    )

    md = render_markdown(results, summary)
    print()
    print(md)
    print()
    print(f"Wrote {out_path}")

    judge_totals = judge_llm.get_token_usage()
    print(
        f"Judge token cost: {judge_totals.total_tokens} tokens, ${judge_totals.estimated_cost_usd:.4f}"
    )

    return 0


def main():
    parser = argparse.ArgumentParser(description="Run LLM-judge eval on the golden set.")
    parser.add_argument("--url", default="http://localhost:8000", help="Server base URL.")
    parser.add_argument("--limit", type=int, default=0, help="Run only the first N queries.")
    parser.add_argument("--filter", default="", help="Only run queries with IDs starting with this string.")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent API calls.")
    parser.add_argument("--timeout", type=float, default=180.0, help="Per-request timeout (seconds).")
    parser.add_argument("--judge-model", default=None, help="Model name override for the judge LLM.")
    parser.add_argument("--label", default="", help="Optional label appended to the results filename.")
    args = parser.parse_args()

    rc = asyncio.run(main_async(args))
    sys.exit(rc)


if __name__ == "__main__":
    main()
