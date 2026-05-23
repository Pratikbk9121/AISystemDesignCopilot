"""
Intent Detector Module

Classifies user queries as either NEW_DESIGN or REFINEMENT.
This module provides a seam for Intent Detection logic, making it testable and swappable.
"""
from enum import Enum
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class Intent(Enum):
    """
    User intent classification for Design Generation vs Refinement.
    
    NEW_DESIGN: User wants to generate a fresh architecture
    REFINEMENT: User wants to modify an existing architecture in the conversation
    """
    NEW_DESIGN = "new_design"
    REFINEMENT = "refinement"


class IntentDetector:
    """
    Module for detecting user intent (NEW_DESIGN vs REFINEMENT).
    
    Interface (what callers see):
        intent = intent_detector.detect(query, has_previous_architecture)
        if intent == Intent.REFINEMENT:
            # Modify existing architecture
        else:
            # Generate new architecture
    
    Implementation (what callers don't see):
        - Keyword matching for refinement signals
        - Previous architecture existence check
        - Combining both signals for decision
        
    Future: Could be replaced with ML-based intent classification
    without changing the interface.
    """

    # Refinement keywords - signals that user wants to modify existing design
    REFINEMENT_KEYWORDS = [
        "scale", "improve", "modify", "change", "add", "remove",
        "update", "enhance", "optimize", "what if", "instead",
        "make it", "can you", "how about", "replace", "swap"
    ]

    def detect(
        self,
        query: str,
        has_previous_architecture: bool
    ) -> Intent:
        """
        Detect whether user wants NEW_DESIGN or REFINEMENT.
        
        Logic:
        - If no previous architecture exists → always NEW_DESIGN
        - If previous architecture exists + query contains refinement keywords → REFINEMENT
        - Otherwise → NEW_DESIGN (explicit new request)
        
        Args:
            query: User's system design query
            has_previous_architecture: Whether conversation has a previous architecture
            
        Returns:
            Intent.NEW_DESIGN or Intent.REFINEMENT
        """
        # No previous architecture → must be new design
        if not has_previous_architecture:
            logger.debug("Intent: NEW_DESIGN (no previous architecture)")
            return Intent.NEW_DESIGN
        
        # Check for refinement keywords
        query_lower = query.lower()
        has_refinement_keyword = any(
            keyword in query_lower 
            for keyword in self.REFINEMENT_KEYWORDS
        )
        
        if has_refinement_keyword:
            logger.debug(
                "Intent: REFINEMENT (has previous + refinement keywords detected)"
            )
            return Intent.REFINEMENT
        else:
            # Has previous arch but no refinement keywords → assume new design
            logger.debug(
                "Intent: NEW_DESIGN (has previous but no refinement keywords)"
            )
            return Intent.NEW_DESIGN

    def is_refinement(
        self,
        query: str,
        has_previous_architecture: bool
    ) -> bool:
        """
        Convenience method that returns boolean instead of enum.
        
        Args:
            query: User's system design query
            has_previous_architecture: Whether conversation has a previous architecture
            
        Returns:
            True if REFINEMENT, False if NEW_DESIGN
        """
        return self.detect(query, has_previous_architecture) == Intent.REFINEMENT
