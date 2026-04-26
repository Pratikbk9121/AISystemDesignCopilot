"""
LLM Client using LangChain for unified interface to OpenAI/Anthropic
"""
from typing import Any, Dict, List
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate

from app.core.config import settings
from app.models.schemas import TokenUsage


class LLMClient:
    """
    Unified LLM client using LangChain.
    Supports OpenAI and Anthropic with consistent interface.
    """
    
    def __init__(self, provider: str | None = None, model: str | None = None):
        """
        Initialize LLM client
        
        Args:
            provider: LLM provider ('openai' or 'anthropic')
            model: Specific model name (optional, uses config defaults)
        """
        self.provider = provider or settings.llm_provider
        self.model = model or self._get_default_model()
        self.llm = self._initialize_llm()
    
    def _get_default_model(self) -> str:
        """Get default model based on provider"""
        if self.provider == "openai":
            return settings.openai_model
        elif self.provider == "anthropic":
            return settings.anthropic_model
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    def _initialize_llm(self) -> BaseChatModel:
        """
        Initialize the appropriate LangChain LLM based on provider

        Returns:
            LangChain chat model instance
        """
        common_params = {
            "temperature": settings.temperature,
            "max_tokens": settings.max_tokens,
            "timeout": settings.llm_timeout,
            "max_retries": settings.max_retries,
        }

        if self.provider == "openai":
            if not settings.openai_api_key or settings.openai_api_key == "your_openai_api_key_here":
                raise ValueError(
                    "OpenAI API key not configured. Please set OPENAI_API_KEY in your .env file.\n"
                    "Get your API key from: https://platform.openai.com/api-keys"
                )

            return ChatOpenAI(
                model=self.model,
                api_key=settings.openai_api_key,
                **common_params
            )

        elif self.provider == "anthropic":
            if not settings.anthropic_api_key or settings.anthropic_api_key == "your_anthropic_api_key_here":
                raise ValueError(
                    "Anthropic API key not configured. Please set ANTHROPIC_API_KEY in your .env file.\n"
                    "Get your API key from: https://console.anthropic.com/"
                )
            
            return ChatAnthropic(
                model=self.model,
                api_key=settings.anthropic_api_key,
                **common_params
            )
        
        else:
            raise ValueError(f"Unsupported provider: {self.provider}")
    
    async def generate(
        self,
        prompt: str | ChatPromptTemplate,
        input_variables: Dict[str, Any] | None = None,
        system_message: str | None = None,
    ) -> str:
        """
        Generate text completion
        
        Args:
            prompt: Prompt string or template
            input_variables: Variables to format the prompt
            system_message: Optional system message
        
        Returns:
            Generated text
        """
        messages = []
        
        if system_message:
            messages.append(SystemMessage(content=system_message))
        
        if isinstance(prompt, ChatPromptTemplate):
            formatted_messages = prompt.format_messages(**(input_variables or {}))
            messages.extend(formatted_messages)
        else:
            messages.append(HumanMessage(content=prompt))
        
        response = await self.llm.ainvoke(messages)
        return response.content
    
    async def generate_structured(
        self,
        prompt: str | ChatPromptTemplate,
        input_variables: Dict[str, Any] | None = None,
        system_message: str | None = None,
        schema: type | None = None,
    ) -> Dict[str, Any]:
        """
        Generate structured JSON output
        
        Args:
            prompt: Prompt string or template
            input_variables: Variables to format the prompt
            system_message: Optional system message
            schema: Pydantic model for structured output (if supported)
        
        Returns:
            Parsed JSON dictionary
        """
        # Use structured output if the model supports it
        if schema and hasattr(self.llm, "with_structured_output"):
            structured_llm = self.llm.with_structured_output(schema)
            
            messages = []
            if system_message:
                messages.append(SystemMessage(content=system_message))
            
            if isinstance(prompt, ChatPromptTemplate):
                formatted_messages = prompt.format_messages(**(input_variables or {}))
                messages.extend(formatted_messages)
            else:
                messages.append(HumanMessage(content=prompt))
            
            result = await structured_llm.ainvoke(messages)
            return result.dict() if hasattr(result, 'dict') else result
        
        # Fallback to JSON parsing
        parser = JsonOutputParser()
        
        # Add JSON format instruction to prompt
        json_instruction = "\n\nIMPORTANT: Respond with valid JSON only. No markdown, no explanation."
        
        if isinstance(prompt, str):
            prompt = prompt + json_instruction
        
        response_text = await self.generate(prompt, input_variables, system_message)
        
        # Clean response (remove markdown code blocks if present)
        cleaned = response_text.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        if cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        cleaned = cleaned.strip()
        
        return parser.parse(cleaned)
    
    def get_token_usage(self, response: Any) -> TokenUsage:
        """
        Extract token usage from LLM response
        
        Args:
            response: LLM response object
        
        Returns:
            TokenUsage object
        """
        # LangChain wraps usage in response metadata
        usage = getattr(response, 'usage_metadata', None) or {}
        
        prompt_tokens = usage.get('input_tokens', 0)
        completion_tokens = usage.get('output_tokens', 0)
        total_tokens = prompt_tokens + completion_tokens
        
        # Estimate cost (rough approximation)
        estimated_cost = self._estimate_cost(prompt_tokens, completion_tokens)
        
        return TokenUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            estimated_cost_usd=estimated_cost
        )
    
    def _estimate_cost(self, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate API cost based on token usage"""
        # Pricing as of 2024 (rough estimates)
        if self.provider == "openai":
            if "gpt-4" in self.model.lower():
                return (prompt_tokens * 0.00003 + completion_tokens * 0.00006)
            else:  # gpt-3.5
                return (prompt_tokens * 0.0000005 + completion_tokens * 0.0000015)
        elif self.provider == "anthropic":
            return (prompt_tokens * 0.00003 + completion_tokens * 0.00015)
        
        return 0.0
