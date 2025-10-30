"""
Prediction Context Manager - Tracks prediction history for sequential processing.

This module maintains context of all predictions made during questionnaire analysis,
allowing the LLM to consider previous decisions when making new predictions.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from collections import OrderedDict

logger = logging.getLogger(__name__)


class PredictionContext:
    """
    Manages prediction context for sequential questionnaire processing.

    Stores each prediction with its reasoning, RAG sources, and metadata
    to provide context for subsequent predictions.
    """

    def __init__(self, session_id: str):
        """
        Initialize prediction context for a session.

        Args:
            session_id: Unique session identifier
        """
        self.session_id = session_id
        self.predictions: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

        # Section-based context tracking
        self.sections: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self.current_section_id: Optional[str] = None
        self.current_section_predictions: Dict[str, Any] = {}
        self.current_section_reasoning: Dict[str, str] = {}

    def add_prediction(
        self,
        question_id: str,
        question_text: str,
        predicted_answer: Any,
        reasoning: str,
        confidence: str = "medium",
        rag_used: bool = False,
        rag_sources: Optional[List[str]] = None,
        rag_chunks: Optional[List[Dict]] = None,
        metadata: Optional[Dict] = None
    ) -> None:
        """
        Add a new prediction to the context.

        Args:
            question_id: Question identifier
            question_text: The actual question
            predicted_answer: The predicted answer (string or list)
            reasoning: AI's reasoning for this prediction
            confidence: Confidence level (high/medium/low)
            rag_used: Whether RAG was used for this prediction
            rag_sources: List of source document names used
            rag_chunks: Full RAG chunk data (optional)
            metadata: Additional metadata
        """
        self.predictions[question_id] = {
            "question_id": question_id,
            "question_text": question_text,
            "predicted_answer": predicted_answer,
            "reasoning": reasoning,
            "confidence": confidence,
            "rag_used": rag_used,
            "rag_sources": rag_sources or [],
            "rag_chunks": rag_chunks or [],
            "metadata": metadata or {},
            "timestamp": datetime.now().isoformat()
        }
        self.updated_at = datetime.now()

        logger.info(
            f"Added prediction for {question_id}: {predicted_answer} "
            f"(RAG: {'Yes' if rag_used else 'No'})"
        )

    def get_prediction(self, question_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific prediction by question ID.

        Args:
            question_id: Question identifier

        Returns:
            Prediction dictionary or None if not found
        """
        return self.predictions.get(question_id)

    def has_prediction(self, question_id: str) -> bool:
        """Check if prediction exists for a question."""
        return question_id in self.predictions

    def get_context_summary(
        self,
        include_reasoning: bool = True,
        include_sources: bool = False,
        max_predictions: Optional[int] = None
    ) -> str:
        """
        Generate a formatted context summary for LLM.

        This provides previous predictions as context for analyzing
        the next question.

        Args:
            include_reasoning: Include AI reasoning for each prediction
            include_sources: Include RAG source documents
            max_predictions: Limit to most recent N predictions (None = all)

        Returns:
            Formatted context string
        """
        if not self.predictions:
            return "No previous predictions yet."

        # Get predictions (most recent first if limited)
        predictions_list = list(self.predictions.values())
        if max_predictions:
            predictions_list = predictions_list[-max_predictions:]

        context_parts = []

        for pred in predictions_list:
            qid = pred['question_id']
            question = pred['question_text']
            answer = pred['predicted_answer']
            reasoning = pred['reasoning']
            rag_used = pred['rag_used']
            sources = pred.get('rag_sources', [])

            # Format answer (handle lists)
            if isinstance(answer, list):
                answer_str = ", ".join(answer)
            else:
                answer_str = str(answer)

            # Build context entry
            context = f"Question [{qid}]: {question}\n"
            context += f"Selected Answer: {answer_str}"

            if include_reasoning and reasoning:
                context += f"\nReasoning: {reasoning}"

            if include_sources and rag_used and sources:
                context += f"\nBased on: {', '.join(sources)}"

            context_parts.append(context)

        return "\n\n".join(context_parts)

    def get_narrative_context(self) -> str:
        """
        Generate a narrative-style context summary.

        Converts predictions into a flowing narrative rather than
        structured Q&A format.

        Returns:
            Narrative context string
        """
        if not self.predictions:
            return ""

        narrative_parts = []

        for pred in self.predictions.values():
            question = pred['question_text']
            answer = pred['predicted_answer']

            # Convert to narrative form
            if "how" in question.lower():
                narrative = f"The organization is {answer}"
            elif "does" in question.lower() or "is" in question.lower():
                narrative = f"Regarding '{question}': {answer}"
            else:
                narrative = f"For {question}: {answer}"

            narrative_parts.append(narrative)

        return ". ".join(narrative_parts) + "."

    def get_all_rag_sources(self) -> List[str]:
        """
        Get all unique RAG sources used across all predictions.

        Returns:
            List of unique source document names
        """
        sources = set()
        for pred in self.predictions.values():
            if pred.get('rag_used'):
                sources.update(pred.get('rag_sources', []))
        return sorted(list(sources))

    def get_statistics(self) -> Dict[str, Any]:
        """
        Get statistics about predictions made.

        Returns:
            Dictionary with stats:
                - total_predictions: Number of predictions made
                - rag_used_count: How many used RAG
                - unique_rag_sources: Number of unique documents consulted
                - average_confidence: Average confidence level
        """
        if not self.predictions:
            return {
                "total_predictions": 0,
                "rag_used_count": 0,
                "unique_rag_sources": 0,
                "high_confidence_count": 0,
                "medium_confidence_count": 0,
                "low_confidence_count": 0
            }

        rag_count = sum(1 for p in self.predictions.values() if p.get('rag_used'))
        confidence_counts = {"high": 0, "medium": 0, "low": 0}

        for pred in self.predictions.values():
            conf = pred.get('confidence', 'medium')
            if conf in confidence_counts:
                confidence_counts[conf] += 1

        return {
            "total_predictions": len(self.predictions),
            "rag_used_count": rag_count,
            "unique_rag_sources": len(self.get_all_rag_sources()),
            "high_confidence_count": confidence_counts['high'],
            "medium_confidence_count": confidence_counts['medium'],
            "low_confidence_count": confidence_counts['low']
        }

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert context to dictionary for serialization.

        Returns:
            Dictionary representation
        """
        return {
            "session_id": self.session_id,
            "predictions": dict(self.predictions),
            "statistics": self.get_statistics(),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat()
        }

    def from_dict(self, data: Dict[str, Any]) -> None:
        """
        Load context from dictionary.

        Args:
            data: Dictionary with predictions data
        """
        self.session_id = data.get('session_id', self.session_id)
        self.predictions = OrderedDict(data.get('predictions', {}))

        # Parse timestamps
        try:
            self.created_at = datetime.fromisoformat(data.get('created_at'))
        except (ValueError, TypeError):
            self.created_at = datetime.now()

        try:
            self.updated_at = datetime.fromisoformat(data.get('updated_at'))
        except (ValueError, TypeError):
            self.updated_at = datetime.now()

        logger.info(
            f"Loaded context with {len(self.predictions)} predictions "
            f"for session {self.session_id}"
        )

    def clear(self) -> None:
        """Clear all predictions."""
        self.predictions.clear()
        self.updated_at = datetime.now()
        logger.info(f"Cleared prediction context for session {self.session_id}")

    # Section-based context methods for batch processing

    def start_new_section(self, section_id: str, section_title: str) -> None:
        """
        Start tracking a new section.

        Args:
            section_id: Section identifier (e.g., "SEC_BS")
            section_title: Section title (e.g., "BUSINESS STRUCTURE")
        """
        self.current_section_id = section_id
        self.current_section_predictions = {}
        self.current_section_reasoning = {}

        logger.info(f"Started new section: {section_id} - {section_title}")

    def add_section_predictions(
        self,
        predictions: Dict[str, Any],
        reasoning: Dict[str, str],
        rag_metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add batch predictions for current section.

        Args:
            predictions: Dictionary mapping question_id to answer
            reasoning: Dictionary mapping question_id to reasoning
            rag_metadata: RAG retrieval metadata (sources, chunks, etc.)
        """
        if self.current_section_id is None:
            logger.warning("No active section - call start_new_section first")
            return

        self.current_section_predictions.update(predictions)
        self.current_section_reasoning.update(reasoning)

        # Also add to main predictions dict
        for qid, answer in predictions.items():
            self.predictions[qid] = {
                "question_id": qid,
                "predicted_answer": answer,
                "reasoning": reasoning.get(qid, ""),
                "section_id": self.current_section_id,
                "rag_metadata": rag_metadata or {},
                "timestamp": datetime.now().isoformat()
            }

        logger.info(f"Added {len(predictions)} predictions to section {self.current_section_id}")

    def finalize_section(self) -> str:
        """
        Finalize current section and return updated context.

        Generates section summary and compresses old sections if needed.

        Returns:
            Updated context string for next section
        """
        if self.current_section_id is None:
            return self._build_context_string()

        # Generate section summary
        section_summary = self._summarize_section(
            self.current_section_id,
            self.current_section_predictions,
            self.current_section_reasoning
        )

        # Store section
        self.sections[self.current_section_id] = {
            "section_id": self.current_section_id,
            "predictions": self.current_section_predictions.copy(),
            "reasoning": self.current_section_reasoning.copy(),
            "summary": section_summary,
            "timestamp": datetime.now().isoformat()
        }

        logger.info(f"Finalized section {self.current_section_id} with {len(self.current_section_predictions)} predictions")

        # Build context string with compression
        context_string = self._build_context_string()

        # Reset current section
        self.current_section_id = None
        self.current_section_predictions = {}
        self.current_section_reasoning = {}

        return context_string

    def _build_context_string(self) -> str:
        """
        Build context string with smart compression.

        Strategy:
        - Keep most recent section in full detail
        - Keep previous section in full detail
        - Compress older sections to summaries
        - Max total context: ~2000 tokens (~3000 characters)

        Returns:
            Formatted context string
        """
        if not self.sections:
            return ""

        context_parts = []
        section_ids = list(self.sections.keys())

        # Recent sections (last 2) - full detail
        recent_sections = section_ids[-2:]  # Last 2 sections
        older_sections = section_ids[:-2]   # Everything before

        # Add recent sections with full detail
        if recent_sections:
            context_parts.append("[RECENT SECTIONS - Full Detail]")
            for section_id in recent_sections:
                section_data = self.sections[section_id]
                section_context = self._format_section_detail(section_data)
                context_parts.append(section_context)

        # Add older sections as summaries
        if older_sections:
            context_parts.append("\n[OLDER SECTIONS - Summarized]")
            for section_id in older_sections:
                section_data = self.sections[section_id]
                summary = section_data.get('summary', '')
                context_parts.append(f"- {summary}")

        full_context = "\n\n".join(context_parts)

        # Compress if too large
        if len(full_context) > 3000:
            full_context = self._compress_context(full_context)

        return full_context

    def _format_section_detail(self, section_data: Dict[str, Any]) -> str:
        """
        Format section with full prediction details.

        Args:
            section_data: Section dictionary

        Returns:
            Formatted section string
        """
        section_id = section_data['section_id']
        predictions = section_data['predictions']
        reasoning = section_data['reasoning']

        parts = [f"Section: {section_id}"]

        for qid, answer in predictions.items():
            reason = reasoning.get(qid, "")
            # Format answer
            if isinstance(answer, list):
                answer_str = ", ".join(str(a) for a in answer)
            else:
                answer_str = str(answer)

            parts.append(f"- {qid}: {answer_str}")
            if reason and len(reason) < 200:  # Only include short reasoning
                parts.append(f"  Reasoning: {reason}")

        return "\n".join(parts)

    def _summarize_section(
        self,
        section_id: str,
        predictions: Dict[str, Any],
        reasoning: Dict[str, str]
    ) -> str:
        """
        Create one-line summary of section decisions.

        Args:
            section_id: Section identifier
            predictions: Section predictions
            reasoning: Section reasoning

        Returns:
            One-line summary string
        """
        # Extract key decisions
        key_decisions = []
        for qid, answer in predictions.items():
            if isinstance(answer, list):
                if len(answer) <= 3:
                    key_decisions.append(", ".join(str(a) for a in answer))
                else:
                    key_decisions.append(f"{len(answer)} items selected")
            else:
                key_decisions.append(str(answer))

        # Limit to first 3 decisions
        decision_str = "; ".join(key_decisions[:3])
        if len(key_decisions) > 3:
            decision_str += f" (+ {len(key_decisions) - 3} more)"

        summary = f"{section_id}: {decision_str}"

        return summary

    def _compress_context(self, context: str) -> str:
        """
        Compress context by keeping only most recent section in detail.

        Args:
            context: Full context string

        Returns:
            Compressed context string
        """
        if not self.sections:
            return context

        # Keep only the very last section in full detail
        section_ids = list(self.sections.keys())
        last_section_id = section_ids[-1]
        last_section = self.sections[last_section_id]

        compressed_parts = []

        # Summaries of all older sections
        older_summaries = []
        for section_id in section_ids[:-1]:
            section_data = self.sections[section_id]
            older_summaries.append(section_data.get('summary', section_id))

        if older_summaries:
            compressed_parts.append("[PREVIOUS SECTIONS]")
            compressed_parts.append("\n".join(f"- {s}" for s in older_summaries))

        # Full detail of last section
        compressed_parts.append("\n[CURRENT SECTION - Detail]")
        compressed_parts.append(self._format_section_detail(last_section))

        return "\n\n".join(compressed_parts)

    def get_section_context(self, include_current: bool = True) -> str:
        """
        Get context string optimized for section-based processing.

        Args:
            include_current: Include current section predictions

        Returns:
            Formatted context string
        """
        context = self._build_context_string()

        # Add current section if requested
        if include_current and self.current_section_id:
            current_parts = [f"\n[CURRENT SECTION: {self.current_section_id}]"]
            for qid, answer in self.current_section_predictions.items():
                reason = self.current_section_reasoning.get(qid, "")
                current_parts.append(f"- {qid}: {answer}")
                if reason and len(reason) < 150:
                    current_parts.append(f"  Reasoning: {reason}")

            context += "\n" + "\n".join(current_parts)

        return context


# Context registry for managing multiple sessions
_context_registry: Dict[str, PredictionContext] = {}


def get_or_create_context(session_id: str) -> PredictionContext:
    """
    Get existing context or create new one for session.

    Args:
        session_id: Session identifier

    Returns:
        PredictionContext instance
    """
    if session_id not in _context_registry:
        _context_registry[session_id] = PredictionContext(session_id)
        logger.info(f"Created new prediction context for session {session_id}")
    return _context_registry[session_id]


def clear_context(session_id: str) -> bool:
    """
    Clear context for a session.

    Args:
        session_id: Session identifier

    Returns:
        True if context existed and was cleared, False otherwise
    """
    if session_id in _context_registry:
        del _context_registry[session_id]
        logger.info(f"Cleared context for session {session_id}")
        return True
    return False


def get_active_sessions() -> List[str]:
    """
    Get list of session IDs with active contexts.

    Returns:
        List of session IDs
    """
    return list(_context_registry.keys())
