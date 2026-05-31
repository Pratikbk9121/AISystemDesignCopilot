# Eval harness

LLM-as-judge evaluation of the System Design Copilot against a golden set of canonical system-design queries.

## Latest run

| Metric | Score |
|---|---|
| **Overall** | **8.73 / 10** |
| In-domain (excludes OOD probes) | 8.61 / 10 |
| Completeness | 8.87 |
| Scalability reasoning | 8.26 |
| Tradeoff coverage | 8.48 |
| Factuality | 9.30 |

- **Tool-use recall:** 6/6 = **100%** — every query with explicit scale numbers triggered `estimate_capacity`.
- **Tool-use precision:** 0.60 — the model occasionally calls the tool with reasonable assumed numbers when grounding the design helps even though numbers weren't given. Counts as soft over-call, not a regression.
- **Out-of-domain refusal accuracy:** 2/3 = 67% — the hallucination guard correctly blocked 2 of 3 deliberately out-of-knowledge probes.
- **Queries:** 23 (6 core + 6 scale-with-numbers + 5 architecture-aspect + 3 refinement + 3 out-of-domain).
- **Judge model:** `gpt-4.1-mini` via Bifrost gateway.
- **Total cost:** ~$0.025 judge + ~$0.15 generation = **~$0.18 per full eval run**.

Full results: see `evals/results/`.

## Golden set

`evals/golden_set.json` — 23 queries covering the 6 documented system topics (Uber, Netflix, Twitter, WhatsApp, Dropbox, URL shortener) plus capacity-tool probes and OOD refusal probes.

Each entry carries:
- `id`, `query`, `topic`
- `expects_tool_call` — whether `estimate_capacity` should fire
- `expects_guard_trigger` — whether the model should refuse via the hallucination guard

## Rubric

The judge ([`evals/judge.py`](judge.py)) scores each response on four 0-10 dimensions:

1. **completeness** — services / data model / API / NFRs covered?
2. **scalability_reasoning** — concrete numbers, sharding strategy, caching reasoning?
3. **tradeoff_coverage** — right tradeoffs named with justification?
4. **factuality** — any invented technologies or wrong claims?

Plus:
- `tool_used` (bool)
- `appropriate_tool_use` (bool)
- `guard_triggered_correctly` (bool | null)
- `one_line_critique`

Overall = mean of the four dimensions.

## Running

```bash
# Start the server (with TEKION_LLM_KEY set in .env)
./run.sh

# In another shell, run the full eval
python scripts/run_evals.py --label baseline

# Smoke test (first 5 queries only)
python scripts/run_evals.py --limit 5 --label smoke

# Filter by id prefix
python scripts/run_evals.py --filter scale- --label scale-only
```

Results land in `evals/results/<timestamp>_<label>.json` with full per-query scores, latencies, token usage, and tool-call transcripts.
