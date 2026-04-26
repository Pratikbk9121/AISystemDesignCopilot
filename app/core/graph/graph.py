"""
LangGraph workflow for system design generation
"""
from typing import Any, Dict, List, Literal
from langgraph.graph import StateGraph, END
from langchain_core.messages import HumanMessage

from app.core.graph.state import SystemDesignState
from app.core.llm.client import LLMClient
from app.core.llm.prompts import PromptTemplates
from app.core.llm.parser import StructuredOutputParser
from app.core.rag import VectorStore, EmbeddingGenerator


class SystemDesignGraph:
    """
    LangGraph-based workflow for system design generation.

    Workflow:
    1. retrieve_context: Fetch relevant docs from vector DB
    2. detect_intent: Determine if this is new design or refinement
    3. generate_design: Generate system architecture
    4. evaluate_design: (optional) Evaluate the design
    5. finalize: Package the response
    """

    def __init__(self):
        """Initialize the graph with all necessary components"""
        self.llm_client = LLMClient()
        self.prompts = PromptTemplates()
        self.parser = StructuredOutputParser()
        self.vector_store = VectorStore(embedding_generator=EmbeddingGenerator())

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """
        Build the LangGraph workflow

        Returns:
            Compiled StateGraph
        """
        workflow = StateGraph(SystemDesignState)

        # Add nodes
        workflow.add_node("retrieve_context", self._retrieve_context)
        workflow.add_node("detect_intent", self._detect_intent)
        workflow.add_node("generate_design", self._generate_design)
        workflow.add_node("evaluate_design", self._evaluate_design)
        workflow.add_node("finalize", self._finalize)

        # Define edges
        workflow.set_entry_point("retrieve_context")
        workflow.add_edge("retrieve_context", "detect_intent")
        workflow.add_edge("detect_intent", "generate_design")

        # Conditional edge: evaluate only if requested
        workflow.add_conditional_edges(
            "generate_design",
            self._should_evaluate,
            {
                "evaluate": "evaluate_design",
                "finalize": "finalize"
            }
        )
        workflow.add_edge("evaluate_design", "finalize")
        workflow.add_edge("finalize", END)

        return workflow.compile()

    async def _retrieve_context(self, state: SystemDesignState) -> Dict[str, Any]:
        """
        Node 1: Retrieve relevant context from vector database
        """
        query = state["query"]

        # Search vector store
        results = self.vector_store.search(query, top_k=5)

        # Extract document content
        retrieved_docs = [doc.content for doc, score in results]

        return {
            "retrieved_documents": retrieved_docs,
            "current_step": "retrieve_context"
        }

    async def _detect_intent(self, state: SystemDesignState) -> Dict[str, Any]:
        """
        Node 2: Detect if this is a new design or refinement of existing
        """
        # Check if there's a previous architecture in conversation
        has_previous = state.get("previous_architecture") is not None

        # Simple heuristic: check for refinement keywords
        query_lower = state["query"].lower()
        refinement_keywords = [
            "scale", "improve", "modify", "change", "add", "remove",
            "update", "enhance", "optimize", "what if", "instead"
        ]

        looks_like_refinement = any(keyword in query_lower for keyword in refinement_keywords)

        is_refinement = has_previous and looks_like_refinement

        return {
            "is_refinement": is_refinement,
            "current_step": "detect_intent"
        }

    async def _generate_design(self, state: SystemDesignState) -> Dict[str, Any]:
        """
        Node 3: Generate system architecture using LLM
        """
        query = state["query"]
        retrieved_context = "\n\n".join(state["retrieved_documents"])
        chat_history = state.get("messages", [])
        additional_context = state.get("additional_context", {})
        is_refinement = state.get("is_refinement", False)

        # Format chat history
        history_str = "\n".join([
            f"{msg['role']}: {msg['content']}"
            for msg in chat_history[-10:]  # Last 10 messages
        ]) if chat_history else "No previous conversation"

        # Format additional context
        context_str = "\n".join([
            f"{key}: {value}"
            for key, value in additional_context.items()
        ]) if additional_context else "No additional context"

        # Choose appropriate prompt template
        if is_refinement and state.get("previous_architecture"):
            prompt_template = self.prompts.get_refinement_prompt()
            input_vars = {
                "current_design": state["previous_architecture"],
                "chat_history": history_str,
                "refinement_query": query,
                "retrieved_context": retrieved_context,
            }
        else:
            prompt_template = self.prompts.get_system_design_prompt()
            input_vars = {
                "retrieved_context": retrieved_context,
                "chat_history": history_str,
                "additional_context": context_str,
                "query": query,
            }

        # Generate using LLM
        response = await self.llm_client.generate_structured(
            prompt=prompt_template,
            input_variables=input_vars,
        )

        # Parse the response
        architecture, explanation = self.parser.parse_system_architecture(response)

        return {
            "architecture_json": architecture.dict(),
            "explanation": explanation,
            "current_step": "generate_design",
            "messages": [
                {"role": "user", "content": query},
                {"role": "assistant", "content": explanation}
            ]
        }

    async def _evaluate_design(self, state: SystemDesignState) -> Dict[str, Any]:
        """
        Node 4: Evaluate the generated design
        """
        query = state["query"]
        architecture = state["architecture_json"]
        retrieved_context = "\n\n".join(state["retrieved_documents"])

        # Prepare evaluation prompt
        prompt_template = self.prompts.get_evaluation_prompt()
        input_vars = {
            "query": query,
            "design": str(architecture),
            "context": retrieved_context,
        }

        # Generate evaluation
        response = await self.llm_client.generate_structured(
            prompt=prompt_template,
            input_variables=input_vars,
        )

        # Parse evaluation
        evaluation = self.parser.parse_evaluation(response)

        return {
            "evaluation_json": evaluation.dict(),
            "current_step": "evaluate_design"
        }

    async def _finalize(self, state: SystemDesignState) -> Dict[str, Any]:
        """
        Node 5: Finalize the response
        """
        return {
            "current_step": "finalize",
            "error": None
        }

    def _should_evaluate(self, state: SystemDesignState) -> Literal["evaluate", "finalize"]:
        """
        Conditional edge: decide whether to evaluate the design
        """
        if state.get("include_evaluation", True):
            return "evaluate"
        return "finalize"

    async def run(
        self,
        query: str,
        session_id: str,
        messages: List[Dict[str, str]] | None = None,
        additional_context: Dict[str, Any] | None = None,
        include_evaluation: bool = True,
        previous_architecture: Dict[str, Any] | None = None,
    ) -> SystemDesignState:
        """
        Run the system design generation workflow

        Args:
            query: User's system design question
            session_id: Session identifier
            messages: Previous conversation messages
            additional_context: Additional context from user
            include_evaluation: Whether to evaluate the design
            previous_architecture: Previous architecture for refinement

        Returns:
            Final state with generated architecture and evaluation
        """
        # Initialize state
        initial_state: SystemDesignState = {
            "query": query,
            "session_id": session_id,
            "additional_context": additional_context or {},
            "include_evaluation": include_evaluation,
            "messages": messages or [],
            "retrieved_documents": [],
            "architecture_json": None,
            "explanation": None,
            "evaluation_json": None,
            "current_step": "start",
            "error": None,
            "token_usage": {},
            "previous_architecture": previous_architecture,
            "is_refinement": False,
        }

        # Run the graph
        final_state = await self.graph.ainvoke(initial_state)

        return final_state
