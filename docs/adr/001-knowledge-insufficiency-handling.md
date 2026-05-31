# ADR 001: Knowledge Insufficiency Handling Strategy

## Status
Accepted

## Context

The AI System Design Copilot uses RAG (Retrieval-Augmented Generation) to provide system design advice based on a curated knowledge base. A critical challenge is handling queries where the knowledge base lacks sufficient information:

### Problem Statement
When a user asks about a system not covered in our knowledge base (e.g., "Design Pinterest" when we only have docs for Uber and Netflix), we face a choice:
1. **Generate anyway** - Risk hallucinating incorrect architecture advice
2. **Refuse to answer** - Better UX than wrong answers, but frustrating
3. **Warn but generate** - Middle ground for medium-confidence scenarios

### Key Concerns
- **Safety**: Incorrect system design advice could lead to production failures
- **Trust**: Users need to trust our answers or know when to be skeptical
- **Usability**: Refusing too often makes the tool less useful
- **Transparency**: Users should understand why we're refusing or warning

## Decision

We implement a **three-tier response strategy** based on confidence scores from the RAG retrieval:

### Tier 1: High Confidence (≥ 0.6) - Generate Normally
- RAG retrieved highly relevant reference patterns
- Generate system design without warnings
- Include confidence metrics in response for transparency

### Tier 2: Medium Confidence (0.3 - 0.6) - Generate with Warning
- RAG retrieved some relevant patterns, but not comprehensive
- **Generate the design** to provide value
- **Include prominent warning** in response:
  - Acknowledge limited knowledge
  - Show confidence score (e.g., 0.45)
  - Recommend validation against production sources
  - Suggest this is a "starting point for research"
- Surface retrieved context so users can judge source quality

### Tier 3: Low Confidence (< 0.3) - Refuse with Guidance
- RAG found minimal or irrelevant content
- **Activate Hallucination Guard** - refuse to generate
- Return structured "insufficient knowledge" response with:
  - Clear explanation of why we're refusing
  - List of available topics in knowledge base
  - Suggested similar topics (if any)
  - Example queries that WOULD work
  - Instructions for expanding knowledge base
- HTTP 200 with `insufficient_knowledge: true` (not 4xx - query was valid)

### Thresholds Chosen

```
Confidence Threshold Values:
- Hallucination Guard: 0.3 (refuse below this)
- Warning Threshold: 0.6 (warn between 0.3-0.6)
- High Confidence: 0.6+ (no warnings)
```

**Rationale:**
- 0.3 threshold prevents egregious hallucinations while allowing speculative but grounded answers
- 0.3-0.6 range provides value while being transparent about limitations
- Thresholds configurable via environment variables for experimentation

## Implementation Details

### Components Modified

1. **Schema Updates** (`app/models/schemas.py`):
   - `SystemDesignResponse.insufficient_knowledge`: Boolean flag
   - `SystemDesignResponse.knowledge_gap_details`: Rich refusal details
   - `SystemDesignResponse.confidence_warning`: Warning message for medium confidence
   - `SystemDesignResponse.architecture`: Now optional (null when refused)

2. **Hallucination Guard** (`app/core/rag/hallucination_guard.py`):
   - Enhanced message quality with available topics
   - Suggests similar topics from knowledge base
   - Provides actionable next steps (API endpoints, examples)

3. **Knowledge Analyzer** (`app/core/knowledge_analyzer.py`):
   - Analyzes vector database to list available topics
   - Suggests similar topics for failed queries
   - Powers new knowledge coverage endpoints

4. **API Endpoints** (`app/api/routes.py`):
   - `GET /api/v1/system-design/knowledge/topics` - List available topics
   - `GET /api/v1/system-design/knowledge/stats` - KB statistics

5. **Orchestrator** (`app/core/orchestrator.py`):
   - Handles hallucination guard triggers gracefully
   - Adds confidence warnings for medium-confidence responses
   - Packages knowledge gap details in response

### Response Examples

**High Confidence (0.85):**
```json
{
  "insufficient_knowledge": false,
  "confidence_warning": null,
  "confidence_metrics": { "overall_confidence": 0.85 },
  "architecture": { ... }
}
```

**Medium Confidence (0.45):**
```json
{
  "insufficient_knowledge": false,
  "confidence_warning": "⚠️ Limited Knowledge Warning: This design is based on medium confidence (score: 0.45)...",
  "confidence_metrics": { "overall_confidence": 0.45 },
  "architecture": { ... }
}
```

**Low Confidence (0.18 - Refused):**
```json
{
  "insufficient_knowledge": true,
  "architecture": null,
  "knowledge_gap_details": {
    "message": "Not enough data",
    "reason": "Low confidence...",
    "available_topics": ["Uber", "Netflix", "Twitter"],
    "similar_topics": ["Twitter"],
    "example_queries": [...]
  }
}
```

## Consequences

### Positive
- ✅ **Safety**: Prevents hallucinated architecture advice on unknown topics
- ✅ **Transparency**: Users know when answers are speculative
- ✅ **Discoverability**: Users learn what topics ARE available
- ✅ **Extensibility**: Easy to add new documents to knowledge base
- ✅ **Measurable**: Confidence scores provide data for tuning thresholds

### Negative
- ❌ **Frustration**: Users may be frustrated by refusals on popular systems
- ❌ **Maintenance**: Knowledge base requires curation and updates
- ❌ **Threshold Sensitivity**: May need tuning based on user feedback

### Mitigations
- Provide rich refusal messages (not just "no")
- Make knowledge base expansion easy (templates, validation scripts)
- Monitor confidence score distribution to tune thresholds
- Offer knowledge coverage API so users can check before querying

## Alternatives Considered

### Alternative 1: Always Generate (No Hallucination Guard)
- **Rejected**: Too risky - users might implement incorrect architectures
- Could work with strong disclaimers, but violates "do no harm"

### Alternative 2: Hard Block Below 0.5
- **Rejected**: Too conservative - would refuse valuable medium-confidence answers
- Users prefer speculative but useful answer with warning over refusal

### Alternative 3: Use LLM to Detect "I Don't Know"
- **Rejected**: LLMs are overconfident and poor at knowing their limits
- Confidence scoring on RAG retrieval is more reliable

### Alternative 4: Web Search Fallback
- **Deferred**: Good future enhancement
- Adds complexity (external API, rate limits, parsing)
- Current approach solves immediate problem, can add later

## Future Enhancements

1. **Adaptive Thresholds**: Learn optimal thresholds from user feedback
2. **Web Search Fallback**: For low-confidence queries, search official docs
3. **User Feedback Loop**: "Was this helpful?" to improve confidence calibration
4. **Knowledge Gap Tracking**: Log refused queries to prioritize doc additions
5. **Auto-Expansion**: Scrape official engineering blogs to auto-populate KB
6. **Multi-Modal RAG**: Include diagrams, videos, code examples

## References

- Hallucination Guard implementation: `app/core/rag/hallucination_guard.py`
- Confidence Scoring: `app/core/rag/confidence_scorer.py`
- Knowledge Analyzer: `app/core/knowledge_analyzer.py`
- Configuration: `app/core/config.py` (CONFIDENCE_THRESHOLD setting)

## Decision Makers

- Architecture Decision: Development Team
- Threshold Values: Based on empirical testing (adjustable)
- Date: 2024-01-XX

## Review Schedule

Review this decision after:
- 1000 production queries (analyze confidence distribution)
- User feedback on refusal rate
- If >20% of queries are refused (threshold may be too high)
- If users report incorrect advice (threshold may be too low)
