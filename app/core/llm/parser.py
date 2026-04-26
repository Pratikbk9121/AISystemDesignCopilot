"""
Structured output parser using LangChain for JSON schema enforcement
"""
from typing import Any, Dict
import json
from langchain_core.output_parsers import JsonOutputParser, PydanticOutputParser
from pydantic import BaseModel, ValidationError

from app.models.schemas import SystemArchitecture, EvaluationResult


class StructuredOutputParser:
    """
    Parses and validates LLM outputs against Pydantic schemas.
    Handles both LangChain's structured output and manual JSON parsing.
    """
    
    @staticmethod
    def parse_system_architecture(response: str | Dict[str, Any]) -> SystemArchitecture:
        """
        Parse LLM response into SystemArchitecture model
        
        Args:
            response: Raw LLM response (string or dict)
        
        Returns:
            SystemArchitecture instance
        
        Raises:
            ValueError: If parsing fails
        """
        try:
            # If already a dict, use it directly
            if isinstance(response, dict):
                data = response
            else:
                # Parse JSON string
                data = StructuredOutputParser._extract_json(response)
            
            # Extract explanation if it's in the JSON
            explanation = data.pop("explanation", "")
            
            # Create SystemArchitecture
            architecture = SystemArchitecture(**data)
            
            return architecture, explanation
        
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Failed to parse system architecture: {str(e)}") from e
    
    @staticmethod
    def parse_evaluation(response: str | Dict[str, Any]) -> EvaluationResult:
        """
        Parse LLM response into EvaluationResult model
        
        Args:
            response: Raw LLM response (string or dict)
        
        Returns:
            EvaluationResult instance
        
        Raises:
            ValueError: If parsing fails
        """
        try:
            if isinstance(response, dict):
                data = response
            else:
                data = StructuredOutputParser._extract_json(response)
            
            return EvaluationResult(**data)
        
        except (json.JSONDecodeError, ValidationError) as e:
            raise ValueError(f"Failed to parse evaluation result: {str(e)}") from e
    
    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """
        Extract JSON from text that may contain markdown code blocks
        
        Args:
            text: Text potentially containing JSON
        
        Returns:
            Parsed JSON dictionary
        """
        # Remove leading/trailing whitespace
        cleaned = text.strip()
        
        # Remove markdown code blocks
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        
        cleaned = cleaned.strip()
        
        # Try to find JSON object boundaries
        start = cleaned.find("{")
        end = cleaned.rfind("}") + 1
        
        if start != -1 and end > start:
            cleaned = cleaned[start:end]
        
        return json.loads(cleaned)
    
    @staticmethod
    def get_pydantic_parser(schema: type[BaseModel]) -> PydanticOutputParser:
        """
        Get a LangChain PydanticOutputParser for a given schema
        
        Args:
            schema: Pydantic model class
        
        Returns:
            Configured PydanticOutputParser
        """
        return PydanticOutputParser(pydantic_object=schema)
    
    @staticmethod
    def get_format_instructions(schema: type[BaseModel]) -> str:
        """
        Get format instructions for a Pydantic schema to include in prompts
        
        Args:
            schema: Pydantic model class
        
        Returns:
            Format instructions string
        """
        parser = PydanticOutputParser(pydantic_object=schema)
        return parser.get_format_instructions()
