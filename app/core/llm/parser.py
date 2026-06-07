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

# Gemini and some other LLMs occasionally emit JSON with trailing commas
# (`..., "Search Service",\n]`). Python's stdlib `json` rejects these, so we
# strip them as a last-chance recovery before raising.
_TRAILING_COMMA_RE = re.compile(r",(\s*[\]}])")


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

    # Coerce list-of-parts payloads (Gemini OpenAI-compat occasionally
    # returns message.content as a list of {"type":"text","text":"..."}
    # parts) into a single string.
    if isinstance(text, list):
        parts: list[str] = []
        for part in text:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
            else:
                parts.append(json.dumps(part))
        text = "".join(parts)

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
    candidate = match.group(1) if match else cleaned
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # 3b. Strip trailing commas (a Gemini-ism) and retry.
    no_trailing = _TRAILING_COMMA_RE.sub(r"\1", candidate)
    try:
        return json.loads(no_trailing)
    except json.JSONDecodeError:
        pass

    # 4. Give up with a useful error. In debug mode, dump the full text to
    # a temp file so the offending LLM output can be inspected; in prod we
    # skip the dump to avoid filling /tmp under sustained parse failures.
    dump_path: str | None = None
    try:
        from app.core.config import settings as _settings
        if _settings.debug:
            import os, tempfile, time
            dump_path = os.path.join(
                tempfile.gettempdir(), f"parse_json_fail_{int(time.time())}.txt"
            )
            try:
                with open(dump_path, "w") as f:
                    f.write(text)
            except Exception:
                dump_path = "<dump failed>"
    except Exception:
        # Settings import shouldn't ever fail here, but if it does we
        # still want to raise the parse error below.
        dump_path = None

    snippet = (text[:300] + "...") if len(text) > 300 else text
    detail = f"Length={len(text)}"
    if dump_path:
        detail += f" dump={dump_path}"
    raise ValueError(
        f"Could not parse JSON from response. {detail} Snippet: {snippet!r}"
    )


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
