"""
Structured output parser for JSON schema enforcement
"""
import json
import re
from typing import Any, Dict, Tuple, Union

from pydantic import ValidationError

from app.models.schemas import EvaluationResult, SystemArchitecture


# Single regex that captures the first balanced-looking JSON object or array.
# Non-greedy with DOTALL so it tolerates newlines and trailing prose.
_JSON_BLOCK_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def parse_json(text: str) -> Any:
    """
    Best-effort JSON parser.

    Strategy:
        1. json.loads(text) on the raw string.
        2. Strip ```json / ``` markdown fences and retry.
        3. Extract the first {...} or [...] block via regex and retry.
        4. Raise ValueError with a truncated snippet of the offending text.

    Args:
        text: Raw LLM response possibly wrapped in markdown / prose.

    Returns:
        Parsed JSON value (dict, list, etc.).

    Raises:
        ValueError: If no fallback succeeds.
    """
    if text is None:
        raise ValueError("parse_json received None")

    # 1. Direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # 2. Strip markdown fences
    cleaned = text.strip()
    if cleaned.startswith("```json"):
        cleaned = cleaned[7:]
    elif cleaned.startswith("```"):
        cleaned = cleaned[3:]
    if cleaned.endswith("```"):
        cleaned = cleaned[:-3]
    cleaned = cleaned.strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. Regex-extract first JSON-looking block
    match = _JSON_BLOCK_RE.search(cleaned)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass

    # 4. Give up with a useful error
    snippet = (text[:300] + "...") if len(text) > 300 else text
    raise ValueError(f"Could not parse JSON from response. Snippet: {snippet!r}")


class StructuredOutputParser:
    """
    Parses and validates LLM outputs against Pydantic schemas.
    Handles JSON extraction from markdown and schema validation.
    """

    @staticmethod
    def parse_system_architecture(
        response: Union[str, Dict[str, Any]]
    ) -> Tuple[SystemArchitecture, str]:
        """
        Parse LLM response into SystemArchitecture model

        Args:
            response: Raw LLM response (string or dict)

        Returns:
            Tuple of (SystemArchitecture instance, explanation string)

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

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            raise ValueError(f"Failed to parse system architecture: {str(e)}") from e

    @staticmethod
    def parse_evaluation(response: Union[str, Dict[str, Any]]) -> EvaluationResult:
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

        except (json.JSONDecodeError, ValidationError, ValueError) as e:
            raise ValueError(f"Failed to parse evaluation result: {str(e)}") from e

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """
        Extract JSON from text that may contain markdown code blocks.

        Thin wrapper around the module-level :func:`parse_json` so all
        JSON parsing in this codebase shares a single implementation.

        Args:
            text: Text potentially containing JSON

        Returns:
            Parsed JSON dictionary
        """
        return parse_json(text)
