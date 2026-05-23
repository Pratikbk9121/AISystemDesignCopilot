"""
LLM-as-judge scoring for system-design responses.

Given a query + the generated response (architecture + explanation),
asks a strong LLM (the same Bifrost gateway as the system under test
but with a stricter, separate prompt) to score on four dimensions
0-10:

    - completeness          — services, data model, API, NFRs covered?
    - scalability_reasoning — specific and credible scaling story?
    - tradeoff_coverage     — right tradeoffs named with justification?
    - factuality            — any made-up technologies or wrong claims?

The judge returns a single JSON object; we parse it into ``JudgeScore``.

When the generator correctly refuses (hallucination guard fires on an
out-of-domain query and ``expects_guard_trigger=True``), the judge is
asked to score that refusal favorably on completeness/factuality.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

from app.core.llm.client import LLMClient
from app.core.llm.parser import parse_json

logger = logging.getLogger(__name__)


JUDGE_SYSTEM_PROMPT = """You are a senior staff engineer grading a junior architect's response to a system-design interview question.

You will receive:
- The QUERY the candidate was given
- The candidate's RESPONSE (a structured architecture + explanation)
- Optional EXPECTATIONS (whether a capacity tool should have fired, whether the candidate should have refused due to insufficient knowledge)

Score the response on FOUR DIMENSIONS, each from 0 to 10:

1. completeness — Did the response cover the essentials for this kind of system?
   • Services / components decomposition
   • Data model / database choice with rationale
   • API surface
   • Non-functional requirements (availability, consistency, latency)
   • For out-of-domain queries where the candidate correctly refused: score 10 if the refusal is honest and helpful, 0 if the candidate hallucinated content.

2. scalability_reasoning — How specific and credible is the scaling story?
   • Concrete numbers (QPS, storage, fanout, partition counts) rather than hand-waving
   • Sharding / partitioning strategy with a justification
   • Caching strategy with hit-ratio reasoning
   • Bottleneck analysis

3. tradeoff_coverage — Are the right tradeoffs named and justified?
   • Consistency vs availability where relevant
   • Push vs pull, fanout-on-write vs read, sync vs async, etc.
   • Each tradeoff should have a clear recommendation, not just "it depends"

4. factuality — Are claims technically correct?
   • No invented technologies / APIs / numbers
   • Performance claims realistic
   • Architectural patterns applied correctly

ALSO REPORT:
- tool_used (bool): did the candidate invoke an estimate_capacity tool call?
- appropriate_tool_use (bool): if the query gave concrete scale numbers, the tool SHOULD have been called. Otherwise it should NOT have been. True = correct behavior.
- guard_triggered_correctly (bool|null): for out-of-domain queries the candidate should refuse via the knowledge-gap path. True if refused, false if hallucinated, null if not an OOD query.
- one_line_critique: a single sentence summarizing the biggest weakness.

OUTPUT FORMAT (strict JSON, no markdown):
{
  "completeness": <int 0-10>,
  "scalability_reasoning": <int 0-10>,
  "tradeoff_coverage": <int 0-10>,
  "factuality": <int 0-10>,
  "tool_used": <bool>,
  "appropriate_tool_use": <bool>,
  "guard_triggered_correctly": <bool|null>,
  "one_line_critique": "<string>"
}

Be honest. Reserve 9-10 for genuinely excellent answers; most reasonable answers should land in the 6-8 range. Penalize generic boilerplate.
"""


@dataclass
class JudgeScore:
    completeness: int
    scalability_reasoning: int
    tradeoff_coverage: int
    factuality: int
    tool_used: bool
    appropriate_tool_use: bool
    guard_triggered_correctly: Optional[bool]
    one_line_critique: str

    @property
    def overall(self) -> float:
        """Mean of the four 0-10 scores."""
        return round(
            (
                self.completeness
                + self.scalability_reasoning
                + self.tradeoff_coverage
                + self.factuality
            )
            / 4.0,
            2,
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["overall"] = self.overall
        return d


def _coerce_int(v: Any, default: int = 0) -> int:
    try:
        return max(0, min(10, int(round(float(v)))))
    except (TypeError, ValueError):
        return default


def _coerce_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"true", "yes", "1"}
    return default


async def judge_response(
    llm: LLMClient,
    query_id: str,
    query: str,
    response_payload: Dict[str, Any],
    expectations: Dict[str, Any],
) -> JudgeScore:
    """
    Score a single API response using LLM-as-judge.

    Args:
        llm: A fresh ``LLMClient`` instance to use for judging.
        query_id: Golden-set query id (logged on error).
        query: The original user query string.
        response_payload: The raw ``SystemDesignResponse`` dict from the API.
        expectations: Subset of the golden-set entry (expects_tool_call,
            expects_guard_trigger, topic).

    Returns:
        A :class:`JudgeScore` with the four dimension scores plus metadata.
    """
    # Build a compact view of the response for the judge — sending the
    # full retrieved_context bloats the prompt without helping the score.
    arch = response_payload.get("architecture")
    response_view: Dict[str, Any] = {
        "architecture": arch,
        "explanation": response_payload.get("explanation"),
        "evaluation": response_payload.get("evaluation"),
        "insufficient_knowledge": response_payload.get("insufficient_knowledge", False),
        "tool_calls": response_payload.get("tool_calls") or [],
        "revision_count": response_payload.get("revision_count", 0),
    }

    user_prompt = (
        f"QUERY:\n{query}\n\n"
        f"EXPECTATIONS:\n{json.dumps(expectations, indent=2)}\n\n"
        f"CANDIDATE RESPONSE:\n{json.dumps(response_view, indent=2, default=str)}\n\n"
        "Score the response per the rubric in your system message. Respond with JSON only."
    )

    raw = await llm.generate_structured(
        prompt=user_prompt,
        system_message=JUDGE_SYSTEM_PROMPT,
        temperature=0.1,  # judge should be near-deterministic
    )

    # ``generate_structured`` returns a dict already, but be defensive.
    if isinstance(raw, str):
        try:
            raw = parse_json(raw)
        except ValueError:
            logger.error("Judge produced unparseable JSON for query %s", query_id)
            raw = {}

    return JudgeScore(
        completeness=_coerce_int(raw.get("completeness")),
        scalability_reasoning=_coerce_int(raw.get("scalability_reasoning")),
        tradeoff_coverage=_coerce_int(raw.get("tradeoff_coverage")),
        factuality=_coerce_int(raw.get("factuality")),
        tool_used=_coerce_bool(raw.get("tool_used")),
        appropriate_tool_use=_coerce_bool(raw.get("appropriate_tool_use")),
        guard_triggered_correctly=(
            None
            if raw.get("guard_triggered_correctly") is None
            else _coerce_bool(raw.get("guard_triggered_correctly"))
        ),
        one_line_critique=str(raw.get("one_line_critique") or ""),
    )
