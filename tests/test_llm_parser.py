"""
Unit tests for app.core.llm.parser.StructuredOutputParser.

Focuses on the JSON-extraction + schema-validation contract, not on the
brittle regex-fix-up paths (those are slated for removal).
"""
import json

import pytest

from app.core.llm.parser import StructuredOutputParser


def _valid_architecture_dict():
    return {
        "services": ["API Gateway", "User Service"],
        "database": "PostgreSQL",
        "scaling_strategy": "Horizontal scaling with sharding",
        "tradeoffs": [],
        "key_components": {"API Gateway": "Routes requests"},
        "data_flow": "Client -> API Gateway -> Services",
        "api_design": ["POST /users"],
        "non_functional_requirements": {"availability": "99.99%"},
        "explanation": "A simple two-service starter design.",
    }


def test_parse_valid_json_string():
    """Plain JSON string parses into a SystemArchitecture and explanation."""
    raw = json.dumps(_valid_architecture_dict())
    arch, explanation = StructuredOutputParser.parse_system_architecture(raw)

    assert arch.services == ["API Gateway", "User Service"]
    assert arch.database == "PostgreSQL"
    assert "two-service" in explanation


def test_parse_dict_input_directly():
    """If a dict is passed in, parser uses it without re-parsing JSON."""
    arch, explanation = StructuredOutputParser.parse_system_architecture(
        _valid_architecture_dict()
    )
    assert arch.scaling_strategy.startswith("Horizontal")
    assert explanation


def test_parse_json_wrapped_in_markdown_fences():
    """JSON inside ```json ... ``` fences is extracted correctly."""
    payload = json.dumps(_valid_architecture_dict())
    fenced = f"```json\n{payload}\n```"
    arch, _explanation = StructuredOutputParser.parse_system_architecture(fenced)
    assert "API Gateway" in arch.services


def test_parse_json_wrapped_in_bare_fences():
    """JSON inside bare ``` fences (no language tag) also parses."""
    payload = json.dumps(_valid_architecture_dict())
    fenced = f"```\n{payload}\n```"
    arch, _explanation = StructuredOutputParser.parse_system_architecture(fenced)
    assert arch.database == "PostgreSQL"


def test_parse_json_embedded_in_prose():
    """JSON object surrounded by chatty prose is found via brace boundaries."""
    payload = json.dumps(_valid_architecture_dict())
    noisy = (
        "Sure! Here's the architecture you asked for:\n\n"
        f"{payload}\n\n"
        "Let me know if you'd like adjustments."
    )
    arch, explanation = StructuredOutputParser.parse_system_architecture(noisy)
    assert arch.services
    assert isinstance(explanation, str)


def test_parse_invalid_input_raises_value_error():
    """Completely non-JSON input raises ValueError."""
    with pytest.raises(ValueError):
        StructuredOutputParser.parse_system_architecture("this is not json at all {{{")


def test_parse_evaluation_invalid_raises_value_error():
    """parse_evaluation surfaces a ValueError on bad payloads."""
    with pytest.raises(ValueError):
        StructuredOutputParser.parse_evaluation("absolutely not json")
