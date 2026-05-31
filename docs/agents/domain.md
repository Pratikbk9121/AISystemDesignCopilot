# Domain Documentation

This repository uses a **single-context** domain documentation layout.

## Structure

- **`docs/CONTEXT.md`** — Domain language and key concepts
- **`docs/adr/`** — Architecture Decision Records (ADRs)

## CONTEXT.md

`docs/CONTEXT.md` defines the **ubiquitous language** for this project — the terms and concepts that make it easier to discuss the codebase.

### Purpose

Instead of verbose explanations:
> "The system uses a multi-step pipeline where we retrieve documents from the vector database using multiple sub-queries, then re-rank them by relevance, calculate confidence scores, and check if we have enough context before generating the design"

Use concise domain terms:
> "Run the Advanced RAG Pipeline with hallucination guard"

### Consumer Rules

Skills that read `CONTEXT.md`:
- `/grill-with-docs` — Updates it as you define new terms
- `/improve-codebase-architecture` — Uses it to understand module boundaries
- `/diagnose` — References it when debugging domain logic
- `/tdd` — Uses domain vocabulary in test names and assertions
- `/zoom-out` — Explains code using domain language

### Example Terms to Define

For the **AI System Design Copilot** project:
- **Advanced RAG Pipeline** — Multi-query retrieval + reranking + confidence scoring
- **Hallucination Guard** — Pre-generation check for context adequacy
- **Design Intent** — Classification of new design vs. refinement
- **Workflow State** — The `SystemDesignState` dictionary flowing through the pipeline
- **Confidence Metrics** — Quality indicators for retrieval results

## Architecture Decision Records (ADRs)

ADRs document **why** you made specific architectural choices.

### Location

All ADRs live in `docs/adr/` with the naming convention:
- `docs/adr/001-decision-title.md`
- `docs/adr/002-another-decision.md`

### Template

```markdown
# ADR-XXX: [Decision Title]

**Date**: YYYY-MM-DD  
**Status**: Accepted | Superseded | Deprecated

## Context

What problem are we solving? What constraints exist?

## Decision

What did we decide to do?

## Consequences

What are the trade-offs? What becomes easier/harder?

## Alternatives Considered

What other options did we evaluate and why did we reject them?
```

### Example ADRs for This Project

- **ADR-001**: Why we chose FAISS over Qdrant initially
- **ADR-002**: Custom workflow vs LangGraph dependency
- **ADR-003**: Multi-query retrieval strategy
- **ADR-004**: Redis caching architecture
- **ADR-005**: Structured output parsing approach

### Consumer Rules

Skills that read ADRs:
- `/grill-with-docs` — Creates new ADRs when you make architectural decisions
- `/improve-codebase-architecture` — References past decisions when suggesting changes
- `/to-prd` — Includes relevant ADRs in PRD context

## Getting Started

If `CONTEXT.md` or `docs/adr/` don't exist yet, run:

```bash
/grill-with-docs
```

This skill will help you create your initial domain language and first ADRs through an interactive interview process.
