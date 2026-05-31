"""
LangGraph-based workflow for system-design generation.

This module replaces the previous hand-rolled async pipeline with a real
``langgraph.graph.StateGraph``.  Nodes are async functions over
:class:`SystemDesignState`; LangGraph merges per-node return dicts back
into the running state.

Flow:

    START
      └─ retrieve_context
           ├─ (hallucination_guard_triggered) → finalize
           └─ detect_intent
                └─ generate_design
                     ├─ (include_evaluation = False) → finalize
                     └─ evaluate_design
                          ├─ (score >= threshold OR revisions exhausted) → finalize
                          └─ revise_design
                               └─ evaluate_design   ← cycle

The reflection cycle is the headline feature: when the evaluator scores
the design below ``settings.reflection_confidence_threshold`` we run an
additional revise pass and re-evaluate, up to ``settings.max_revisions``
total revisions.

Streaming is supported via :meth:`run_streaming`, which adapts LangGraph's
event stream into the SSE event shape the frontend already expects, with
one new event type: ``revision_started``.
"""
from typing import Any, AsyncIterator, Dict, List, Optional
import json
import logging

from langgraph.config import get_stream_writer
from langgraph.graph import StateGraph, START, END

from app.core.graph.state import SystemDesignState
from app.core.llm.client import LLMClient, CachedLLMClient
from app.core.llm.prompts import PromptTemplates
from app.core.llm.parser import StructuredOutputParser, parse_json
from app.core.rag import QdrantVectorStore, ContextRetrieval
from app.core.intent_detector import IntentDetector, Intent
from app.core.dependencies import get_vector_store
from app.core.config import settings
from app.core.tools import TOOL_SPECS, dispatch_tool

logger = logging.getLogger(__name__)


# ============================================================================
# Conditional-edge predicates
# ============================================================================

def _after_retrieve(state: SystemDesignState) -> str:
    """If the hallucination guard fired we short-circuit to finalize."""
    if state.get("hallucination_guard_triggered", False):
        return "finalize"
    return "detect_intent"


def _after_generate(state: SystemDesignState) -> str:
    """Evaluation is opt-in via the request flag."""
    if state.get("include_evaluation", False):
        return "evaluate_design"
    return "finalize"


def _should_revise(state: SystemDesignState) -> str:
    """
    Reflection gate.

    Revise when:
      - reflection is globally enabled,
      - the evaluator returned a confidence score below the threshold,
      - and we haven't already used up ``max_revisions``.
    """
    if not settings.reflection_enabled:
        return "finalize"

    evaluation = state.get("evaluation_json") or {}
    score = float(evaluation.get("confidence_score", 1.0))
    revisions_done = int(state.get("revision_count", 0))

    if (
        score < settings.reflection_confidence_threshold
        and revisions_done < settings.max_revisions
    ):
        logger.info(
            "Reflection triggered: score=%.2f < threshold=%.2f (revision %d/%d)",
            score,
            settings.reflection_confidence_threshold,
            revisions_done + 1,
            settings.max_revisions,
        )
        return "revise_design"
    return "finalize"


# ============================================================================
# The graph
# ============================================================================

class SystemDesignGraph:
    """
    Compiled LangGraph workflow for system-design generation.

    A fresh instance is created per request by the orchestrator; the
    underlying ``LLMClient`` therefore tracks token usage scoped to the
    single user query.

    Public API (preserved from the prior hand-rolled implementation):
        - ``await graph.run(...)`` returns the final state dict
        - ``async for evt in graph.run_streaming(...)`` yields SSE events
    """

    def __init__(self, llm_cache_manager: Optional[object] = None):
        if llm_cache_manager and settings.cache_llm_responses:
            logger.info("Initializing SystemDesignGraph with cached LLM client")
            self.llm_client = CachedLLMClient(cache_manager=llm_cache_manager)
        else:
            self.llm_client = LLMClient()

        self.prompts = PromptTemplates()
        self.parser = StructuredOutputParser()

        vector_store = get_vector_store()
        if vector_store is None:
            logger.warning(
                "Global Qdrant vector store not found, creating new instance "
                "(this will impact performance)"
            )
            vector_store = QdrantVectorStore()

        self.context_retrieval = ContextRetrieval(
            vector_store=vector_store, llm_client=self.llm_client
        )
        self.intent_detector = IntentDetector()

        self.compiled = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        """Wire nodes + edges and compile once at construction time."""
        builder = StateGraph(SystemDesignState)

        builder.add_node("retrieve_context", self._retrieve_context)
        builder.add_node("detect_intent", self._detect_intent)
        builder.add_node("generate_design", self._generate_design)
        builder.add_node("evaluate_design", self._evaluate_design)
        builder.add_node("revise_design", self._revise_design)
        builder.add_node("finalize", self._finalize)

        builder.add_edge(START, "retrieve_context")

        builder.add_conditional_edges(
            "retrieve_context",
            _after_retrieve,
            {"detect_intent": "detect_intent", "finalize": "finalize"},
        )
        builder.add_edge("detect_intent", "generate_design")
        builder.add_conditional_edges(
            "generate_design",
            _after_generate,
            {"evaluate_design": "evaluate_design", "finalize": "finalize"},
        )
        builder.add_conditional_edges(
            "evaluate_design",
            _should_revise,
            {"revise_design": "revise_design", "finalize": "finalize"},
        )
        builder.add_edge("revise_design", "evaluate_design")
        builder.add_edge("finalize", END)

        return builder.compile()

    # ------------------------------------------------------------------
    # Nodes
    # ------------------------------------------------------------------

    async def _retrieve_context(self, state: SystemDesignState) -> Dict[str, Any]:
        """RAG retrieval with multi-query, reranking, confidence + guard."""
        query = state["query"]
        result = await self.context_retrieval.retrieve(
            query=query, quality_threshold=settings.confidence_threshold
        )

        if result.guard_triggered:
            logger.warning("Hallucination guard triggered for query: %s", query[:60])
            return {
                "retrieved_documents": [],
                "confidence_metrics": result.confidence.dict(),
                "hallucination_guard_triggered": True,
                "insufficient_context_response": result.insufficient_response,
                "current_step": "retrieve_context",
            }

        return {
            "retrieved_documents": result.patterns,
            "confidence_metrics": result.confidence.dict(),
            "hallucination_guard_triggered": False,
            "current_step": "retrieve_context",
        }

    async def _detect_intent(self, state: SystemDesignState) -> Dict[str, Any]:
        """Classify NEW_DESIGN vs REFINEMENT."""
        intent = self.intent_detector.detect(
            query=state["query"],
            has_previous_architecture=state.get("previous_architecture") is not None,
        )
        return {
            "is_refinement": intent == Intent.REFINEMENT,
            "current_step": "detect_intent",
        }

    async def _generate_design(self, state: SystemDesignState) -> Dict[str, Any]:
        """
        First-pass LLM generation of the architecture.

        When ``settings.tools_enabled`` is True we run the tool-use loop
        first — the model may call ``estimate_capacity`` (etc.) before
        producing the final JSON design. Tool results are surfaced via
        ``tool_calls`` in the response so the frontend can show them.
        """
        system_message, user_prompt = self._build_design_prompt(state)

        if settings.tools_enabled and TOOL_SPECS:
            # Tool-use path still buffers — the multi-turn loop has to
            # interleave tool_calls/tool messages before the final answer,
            # so per-token streaming isn't meaningful here.
            json_instruction = (
                "\n\nWhen you are done with any tool calls, respond with the final "
                "JSON architecture only — no markdown, no prose."
            )
            response_text, tool_calls = await self.llm_client.generate_with_tools(
                prompt=user_prompt + json_instruction,
                system_message=system_message,
                tools=TOOL_SPECS,
                tool_dispatcher=dispatch_tool,
                max_iterations=settings.tool_max_iterations,
            )
            response = parse_json(response_text)
        else:
            # Stream LLM tokens out as ``design_chunk`` custom events so
            # /query-stream can forward them as SSE before the node returns
            # (the frontend's IncrementalArchitectureParser consumes partial
            # JSON). When the graph is run via ``ainvoke`` (no streaming
            # consumer), ``get_stream_writer`` still returns a writer but
            # nothing reads the custom channel — effectively a no-op.
            writer = get_stream_writer()

            def _emit_chunk(chunk: str) -> None:
                try:
                    writer({"type": "design_chunk", "data": {"chunk": chunk}})
                except Exception:  # noqa: BLE001 — writer errors must not abort generation
                    logger.exception("design_chunk writer failed")

            response = await self.llm_client.generate_structured_stream(
                prompt=user_prompt,
                system_message=system_message,
                on_chunk=_emit_chunk,
            )
            tool_calls = []

        architecture, explanation = self.parser.parse_system_architecture(response)

        if tool_calls:
            logger.info(
                "generate_design: %d tool call(s) made (%s)",
                len(tool_calls),
                ", ".join(tc["name"] for tc in tool_calls),
            )

        return {
            "architecture_json": architecture.dict(),
            "explanation": explanation,
            "tool_calls": tool_calls,
            "current_step": "generate_design",
            "messages": [
                {"role": "user", "content": state["query"]},
                {"role": "assistant", "content": explanation},
            ],
        }

    async def _evaluate_design(self, state: SystemDesignState) -> Dict[str, Any]:
        """LLM-judge evaluation of the current design."""
        system_message = self.prompts.get_evaluation_prompt()
        user_prompt = self.prompts.format_evaluation_user_prompt(
            query=state["query"],
            design=json.dumps(state["architecture_json"], indent=2),
            context="\n\n".join(state.get("retrieved_documents", [])),
        )
        response = await self.llm_client.generate_structured(
            prompt=user_prompt, system_message=system_message
        )
        evaluation = self.parser.parse_evaluation(response)
        eval_dict = evaluation.dict()

        return {
            "evaluation_json": eval_dict,
            "previous_evaluation": eval_dict,
            "current_step": "evaluate_design",
        }

    async def _revise_design(self, state: SystemDesignState) -> Dict[str, Any]:
        """Revise the design using evaluator feedback."""
        prior_design = state["architecture_json"]
        prior_eval = state.get("previous_evaluation") or state.get("evaluation_json") or {}

        feedback_lines = []
        for w in prior_eval.get("weaknesses", []) or []:
            feedback_lines.append(f"- Weakness: {w}")
        for s in prior_eval.get("suggestions", []) or []:
            feedback_lines.append(f"- Suggestion: {s}")
        if not feedback_lines:
            feedback_lines.append(
                "- Improve overall quality, completeness, and scalability reasoning."
            )
        feedback_str = "\n".join(feedback_lines)

        history_str = self._format_history(state.get("messages", []))
        retrieved_context = "\n\n".join(state.get("retrieved_documents", []))

        system_message = self.prompts.get_revision_prompt()
        user_prompt = self.prompts.format_revision_user_prompt(
            original_query=state["query"],
            prior_design=json.dumps(prior_design, indent=2),
            evaluator_feedback=feedback_str,
            retrieved_context=retrieved_context,
            chat_history=history_str,
        )

        response = await self.llm_client.generate_structured(
            prompt=user_prompt, system_message=system_message
        )
        architecture, explanation = self.parser.parse_system_architecture(response)

        revision_count = int(state.get("revision_count", 0)) + 1
        logger.info("Revision %d complete", revision_count)

        return {
            "architecture_json": architecture.dict(),
            "explanation": explanation,
            "revision_count": revision_count,
            "current_step": "revise_design",
        }

    async def _finalize(self, state: SystemDesignState) -> Dict[str, Any]:
        """Snapshot token usage and mark the run complete."""
        usage = self.llm_client.get_token_usage().dict()
        return {
            "token_usage": usage,
            "current_step": "finalize",
            "error": None,
        }

    # ------------------------------------------------------------------
    # Prompt helpers
    # ------------------------------------------------------------------

    def _format_history(self, messages: List[Dict[str, str]]) -> str:
        if not messages:
            return "No previous conversation"
        return "\n".join(
            f"{msg['role']}: {msg['content']}" for msg in messages[-10:]
        )

    def _build_design_prompt(self, state: SystemDesignState) -> tuple[str, str]:
        """Return (system_message, user_prompt) for the initial generation."""
        retrieved_context = "\n\n".join(state.get("retrieved_documents", []))
        history_str = self._format_history(state.get("messages", []))
        additional_context = state.get("additional_context") or {}
        context_str = (
            "\n".join(f"{k}: {v}" for k, v in additional_context.items())
            if additional_context
            else "No additional context"
        )

        if state.get("is_refinement") and state.get("previous_architecture"):
            system_message = self.prompts.get_refinement_prompt()
            user_prompt = self.prompts.format_refinement_user_prompt(
                current_design=state["previous_architecture"],
                refinement_query=state["query"],
                chat_history=history_str,
                retrieved_context=retrieved_context,
            )
        else:
            system_message = self.prompts.get_system_design_prompt()
            user_prompt = self.prompts.format_system_design_user_prompt(
                query=state["query"],
                retrieved_context=retrieved_context,
                chat_history=history_str,
                additional_context=context_str,
            )
        return system_message, user_prompt

    # ------------------------------------------------------------------
    # Public entrypoints
    # ------------------------------------------------------------------

    @staticmethod
    def _initial_state(
        query: str,
        session_id: str,
        messages: List[Dict[str, str]] | None,
        additional_context: Dict[str, Any] | None,
        include_evaluation: bool,
        previous_architecture: Dict[str, Any] | None,
    ) -> SystemDesignState:
        return {
            "query": query,
            "session_id": session_id,
            "additional_context": additional_context or {},
            "include_evaluation": include_evaluation,
            "messages": messages or [],
            "retrieved_documents": [],
            "architecture_json": None,
            "explanation": None,
            "evaluation_json": None,
            "revision_count": 0,
            "should_revise": False,
            "previous_evaluation": None,
            "token_usage": None,
            "tool_calls": [],
            "current_step": "start",
            "error": None,
            "previous_architecture": previous_architecture,
            "is_refinement": False,
            "hallucination_guard_triggered": False,
            "insufficient_context_response": {},
            "confidence_metrics": {},
        }

    async def run(
        self,
        query: str,
        session_id: str,
        messages: List[Dict[str, str]] | None = None,
        additional_context: Dict[str, Any] | None = None,
        include_evaluation: bool = True,
        previous_architecture: Dict[str, Any] | None = None,
    ) -> SystemDesignState:
        """Run the full graph and return the final state."""
        initial = self._initial_state(
            query, session_id, messages, additional_context,
            include_evaluation, previous_architecture,
        )
        try:
            final_state: SystemDesignState = await self.compiled.ainvoke(initial)
            return final_state
        except Exception as e:
            logger.error("Error in system design workflow: %s", e, exc_info=True)
            initial["error"] = str(e)
            initial["current_step"] = "error"
            # Best-effort token snapshot even on failure.
            try:
                initial["token_usage"] = self.llm_client.get_token_usage().dict()
            except Exception:
                pass
            return initial

    async def run_streaming(
        self,
        query: str,
        session_id: str,
        messages: List[Dict[str, str]] | None = None,
        additional_context: Dict[str, Any] | None = None,
        include_evaluation: bool = True,
        previous_architecture: Dict[str, Any] | None = None,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Stream graph progress as SSE-shaped events.

        Adapts LangGraph's node-level events into the event types the
        frontend already understands (``progress``, ``design_complete``,
        ``evaluation``, ``error``), plus a new ``revision_started`` event
        emitted when the graph enters the revise node.
        """
        initial = self._initial_state(
            query, session_id, messages, additional_context,
            include_evaluation, previous_architecture,
        )

        try:
            async for stream_mode, payload in self.compiled.astream(
                initial, stream_mode=["updates", "custom"]
            ):
                # ``custom`` carries per-token events emitted by nodes via
                # ``get_stream_writer``. Forward them as-is — they already
                # match the SSE event vocabulary (``design_chunk`` today).
                if stream_mode == "custom":
                    if isinstance(payload, dict) and payload.get("type"):
                        yield payload
                    continue

                # ``updates``: dict of {node_name: returned_state_partial}.
                event = payload
                for node_name, update in event.items():
                    if not isinstance(update, dict):
                        continue

                    if node_name == "retrieve_context":
                        if update.get("hallucination_guard_triggered"):
                            yield {
                                "type": "error",
                                "data": {
                                    "message": "Insufficient context to generate design",
                                    "step": "retrieve_context",
                                },
                            }
                        else:
                            yield {
                                "type": "progress",
                                "data": {
                                    "step": "rag_complete",
                                    "message": f"Retrieved {len(update.get('retrieved_documents', []))} documents",
                                },
                            }

                    elif node_name == "detect_intent":
                        yield {
                            "type": "progress",
                            "data": {
                                "step": "intent_detected",
                                "is_refinement": update.get("is_refinement", False),
                            },
                        }

                    elif node_name == "generate_design":
                        for tc in update.get("tool_calls") or []:
                            yield {"type": "tool_call", "data": tc}
                        yield {
                            "type": "design_complete",
                            "data": {
                                "architecture": update.get("architecture_json"),
                                "explanation": update.get("explanation"),
                                "tool_calls": update.get("tool_calls") or [],
                            },
                        }

                    elif node_name == "revise_design":
                        yield {
                            "type": "revision_started",
                            "data": {
                                "revision_count": update.get("revision_count", 0),
                            },
                        }
                        yield {
                            "type": "design_complete",
                            "data": {
                                "architecture": update.get("architecture_json"),
                                "explanation": update.get("explanation"),
                                "revision_count": update.get("revision_count", 0),
                            },
                        }

                    elif node_name == "evaluate_design":
                        yield {
                            "type": "evaluation",
                            "data": update.get("evaluation_json", {}),
                        }

                    elif node_name == "finalize":
                        yield {
                            "type": "progress",
                            "data": {
                                "step": "finalize",
                                "token_usage": update.get("token_usage"),
                            },
                        }
        except Exception as e:
            logger.error("Error in streaming workflow: %s", e, exc_info=True)
            yield {"type": "error", "data": {"message": str(e)}}
