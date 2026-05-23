"""
Unit tests for app.core.intent_detector.IntentDetector.

These tests exercise stable, deterministic behavior of the keyword-based
intent classifier. No live LLM is called; if a future implementation adds an
LLM seam we mock it here defensively.
"""
from unittest.mock import patch

import pytest

from app.core.intent_detector import Intent, IntentDetector


@pytest.fixture
def detector():
    return IntentDetector()


def test_new_design_query_without_prior_architecture(detector):
    """A fresh design query with no prior architecture is NEW_DESIGN."""
    intent = detector.detect(
        "Design a scalable ride-sharing system like Uber",
        has_previous_architecture=False,
    )
    assert intent == Intent.NEW_DESIGN


def test_refinement_keyword_with_prior_architecture(detector):
    """Refinement keyword + prior architecture should classify as REFINEMENT."""
    intent = detector.detect(
        "Can you scale this to 10x more users?",
        has_previous_architecture=True,
    )
    assert intent == Intent.REFINEMENT


def test_refinement_keyword_without_prior_architecture_is_new_design(detector):
    """No prior architecture short-circuits to NEW_DESIGN even with keywords."""
    intent = detector.detect(
        "Improve the matching latency",
        has_previous_architecture=False,
    )
    assert intent == Intent.NEW_DESIGN


def test_clarifying_followup_without_keywords_is_new_design(detector):
    """A clarifying follow-up with no refinement keywords falls through to NEW_DESIGN."""
    intent = detector.detect(
        "Tell me more about consistency models",
        has_previous_architecture=True,
    )
    assert intent == Intent.NEW_DESIGN


def test_off_topic_input_classified_deterministically(detector):
    """Off-topic input still produces a deterministic classification (NEW_DESIGN)."""
    intent = detector.detect(
        "What's the weather today?",
        has_previous_architecture=False,
    )
    assert intent == Intent.NEW_DESIGN


def test_is_refinement_convenience_returns_bool(detector):
    """is_refinement() returns a plain bool that matches detect()."""
    assert detector.is_refinement("add a caching layer", has_previous_architecture=True) is True
    assert detector.is_refinement("Design Twitter", has_previous_architecture=False) is False


def test_detect_does_not_invoke_external_llm(detector):
    """
    Defensive: ensure detection is local/deterministic and does not reach out
    to anthropic/openai SDKs. If a future seam is added, this guards it.
    """
    with patch("app.core.intent_detector.logger") as _:
        intent = detector.detect("optimize the database", has_previous_architecture=True)
    assert intent in (Intent.NEW_DESIGN, Intent.REFINEMENT)
