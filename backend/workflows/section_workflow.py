"""
Section Analysis Workflow for Temporal.

This module defines the child workflow for processing a single section
with wave-based dynamic question resolution and RAG chunk caching.
"""

from datetime import timedelta
from typing import Dict, Any, List
from dataclasses import dataclass

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from activities.section_analysis import (
        parse_section_structure,
        retrieve_section_chunks,
        predict_question_batch_with_rag,
        resolve_next_questions,
        generate_section_context
    )


@dataclass
class WaveState:
    """State for current wave processing."""
    wave_number: int = 1
    pending_questions: List[Dict[str, Any]] = None
    predictions: Dict[str, Any] = None
    reasoning: Dict[str, str] = None

    def __post_init__(self):
        if self.pending_questions is None:
            self.pending_questions = []
        if self.predictions is None:
            self.predictions = {}
        if self.reasoning is None:
            self.reasoning = {}


@workflow.defn
class SectionAnalysisWorkflow:
    """
    Child workflow for analyzing a single section.

    Processes section with wave-based resolution:
    1. Retrieve RAG chunks once for entire section
    2. Wave 1: Predict root questions
    3. Wave N: Predict revealed questions using cached chunks
    4. Generate section context summary
    """

    def __init__(self):
        """Initialize workflow state."""
        self._wave_state = WaveState()
        self._rag_chunks: List[Dict[str, Any]] = []
        self._rag_metadata: Dict[str, Any] = {}
        self._all_section_questions: List[Dict[str, Any]] = []
        self._section_title = ""
        self._max_waves = 5  # Safety limit

    @workflow.run
    async def run(
        self,
        section_id: str,
        company_data: Dict[str, Any],
        configuration: Dict[str, Any],
        previous_context: str = ""
    ) -> Dict[str, Any]:
        """
        Execute the section analysis workflow.

        Args:
            section_id: Section identifier (e.g., "SEC_BS")
            company_data: Company information dictionary
            configuration: Configuration settings
            previous_context: Context from previous sections

        Returns:
            Dictionary containing:
                - section_id: Section identifier
                - predictions: Predictions dictionary
                - reasoning: Reasoning dictionary
                - rag_metadata: RAG retrieval metadata
                - updated_context: Updated context string for next section
                - waves_executed: Number of waves processed
        """
        workflow.logger.info(f"Starting section analysis workflow for {section_id}")

        # Step 1: Parse section structure
        section_structure = await workflow.execute_activity(
            parse_section_structure,
            section_id,
            start_to_close_timeout=timedelta(seconds=10)
        )

        self._section_title = section_structure['title']
        self._all_section_questions = section_structure['all_questions']
        root_questions = section_structure['root_questions']
        optimal_top_k = section_structure['optimal_top_k']

        workflow.logger.info(
            f"Section {section_id}: {len(self._all_section_questions)} questions, "
            f"{len(root_questions)} root questions, top_k={optimal_top_k}"
        )

        # Step 2: Retrieve RAG chunks for entire section (ONE TIME)
        try:
            rag_result = await workflow.execute_activity(
                retrieve_section_chunks,
                args=[
                    self._section_title,
                    self._all_section_questions,
                    company_data,
                    configuration,
                    previous_context,
                    optimal_top_k
                ],
                start_to_close_timeout=timedelta(seconds=30)
            )

            if rag_result.get('success'):
                self._rag_chunks = rag_result.get('chunks', [])
                self._rag_metadata = {
                    'total_chunks': len(self._rag_chunks),
                    'retrieval_time': rag_result.get('retrieval_time', 0),
                    'sources': rag_result.get('sources', []),
                    'section_query': rag_result.get('section_query', '')
                }
                workflow.logger.info(
                    f"Retrieved {len(self._rag_chunks)} chunks for section in "
                    f"{self._rag_metadata['retrieval_time']:.2f}s"
                )
            else:
                workflow.logger.warning(
                    f"RAG retrieval failed: {rag_result.get('error')}. "
                    "Proceeding with LLM-only predictions."
                )
                self._rag_chunks = []
                self._rag_metadata = {'error': rag_result.get('error')}

        except Exception as e:
            workflow.logger.error(f"RAG retrieval error: {str(e)}")
            self._rag_chunks = []
            self._rag_metadata = {'error': str(e)}

        # Step 3: Wave-based processing
        self._wave_state.pending_questions = root_questions

        while self._wave_state.pending_questions and self._wave_state.wave_number <= self._max_waves:
            workflow.logger.info(
                f"Wave {self._wave_state.wave_number}: "
                f"Processing {len(self._wave_state.pending_questions)} questions"
            )

            # Predict current wave questions
            wave_result = await self._process_wave(
                company_data,
                configuration,
                previous_context
            )

            # Check if any new questions were revealed
            if not wave_result['newly_revealed']:
                workflow.logger.info(f"No new questions revealed. Section complete after {self._wave_state.wave_number} waves")
                break

            # Move to next wave
            self._wave_state.wave_number += 1

        # Check wave limit
        if self._wave_state.wave_number > self._max_waves:
            workflow.logger.warning(
                f"Reached maximum wave limit ({self._max_waves}). "
                "Section may have incomplete predictions."
            )

        # Step 4: Generate section context summary
        updated_context = await workflow.execute_activity(
            generate_section_context,
            args=[
                section_id,
                self._section_title,
                self._wave_state.predictions,
                self._wave_state.reasoning,
                previous_context
            ],
            start_to_close_timeout=timedelta(seconds=10)
        )

        workflow.logger.info(
            f"Section {section_id} completed: {len(self._wave_state.predictions)} predictions "
            f"across {self._wave_state.wave_number} waves"
        )

        return {
            "section_id": section_id,
            "predictions": self._wave_state.predictions,
            "reasoning": self._wave_state.reasoning,
            "rag_metadata": self._rag_metadata,
            "updated_context": updated_context,
            "waves_executed": self._wave_state.wave_number
        }

    async def _process_wave(
        self,
        company_data: Dict[str, Any],
        configuration: Dict[str, Any],
        previous_context: str
    ) -> Dict[str, Any]:
        """
        Process one wave of questions.

        Args:
            company_data: Company information
            configuration: Configuration settings
            previous_context: Previous section context

        Returns:
            Dictionary with wave results and newly revealed questions
        """
        # Predict batch of questions using cached RAG chunks
        prediction_result = await workflow.execute_activity(
            predict_question_batch_with_rag,
            args=[
                self._wave_state.pending_questions,
                self._rag_chunks,  # CACHED from section retrieval
                company_data,
                configuration,
                previous_context,
                self._wave_state.predictions  # Previous predictions in section
            ],
            start_to_close_timeout=timedelta(seconds=60)
        )

        wave_predictions = prediction_result.get('predictions', {})
        wave_reasoning = prediction_result.get('reasoning', {})

        # Add to accumulated predictions
        self._wave_state.predictions.update(wave_predictions)
        self._wave_state.reasoning.update(wave_reasoning)

        workflow.logger.info(
            f"Wave {self._wave_state.wave_number} predictions: {list(wave_predictions.keys())}"
        )

        # Resolve next questions
        newly_revealed_ids = await workflow.execute_activity(
            resolve_next_questions,
            args=[
                self._wave_state.pending_questions,
                wave_predictions,
                self._all_section_questions
            ],
            start_to_close_timeout=timedelta(seconds=5)
        )

        # Get full question objects for newly revealed IDs
        newly_revealed_questions = [
            q for q in self._all_section_questions
            if q['id'] in newly_revealed_ids
        ]

        # Update pending questions for next wave
        self._wave_state.pending_questions = newly_revealed_questions

        return {
            "wave_predictions": wave_predictions,
            "wave_reasoning": wave_reasoning,
            "newly_revealed": newly_revealed_ids
        }
