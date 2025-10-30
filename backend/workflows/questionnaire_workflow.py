"""
Questionnaire Analysis Workflow for Temporal.

This module defines the main workflow for processing entire questionnaire
in section-based batches with context accumulation.
"""

from datetime import timedelta
from typing import Dict, Any, List
from dataclasses import dataclass

from temporalio import workflow

with workflow.unsafe.imports_passed_through():
    from workflows.section_workflow import SectionAnalysisWorkflow
    from activities.section_analysis import send_progress_update, save_questionnaire_results


@dataclass
class QuestionnaireProgress:
    """Progress information for questionnaire analysis."""
    sections_completed: int = 0
    total_sections: int = 0
    predictions_made: int = 0
    current_section: str = ""
    status: str = "running"


@workflow.defn
class QuestionnaireAnalysisWorkflow:
    """
    Main workflow for analyzing entire questionnaire.

    Processes all sections sequentially, accumulating context across sections
    and tracking progress for real-time updates.
    """

    def __init__(self):
        """Initialize workflow state."""
        self._progress = QuestionnaireProgress()
        self._cancelled = False
        self._accumulated_context = ""
        self._all_predictions: Dict[str, Any] = {}
        self._all_reasoning: Dict[str, str] = {}
        self._all_rag_metadata: Dict[str, Any] = {}

    @workflow.run
    async def run(
        self,
        session_id: str,
        sections: List[Dict[str, Any]],
        company_data: Dict[str, Any],
        configuration: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute the questionnaire analysis workflow.

        Args:
            session_id: Unique session identifier
            sections: List of section dictionaries with IDs and metadata
            company_data: Company information dictionary
            configuration: Configuration settings

        Returns:
            Dictionary containing:
                - session_id: Session identifier
                - total_predictions: Number of predictions made
                - sections_processed: Number of sections completed
                - predictions: All predictions dictionary
                - reasoning: All reasoning dictionary
                - rag_metadata: RAG retrieval metadata
                - final_context: Final accumulated context
        """
        workflow.logger.info(
            f"Starting questionnaire analysis workflow for session {session_id} "
            f"with {len(sections)} sections"
        )

        # Initialize progress
        self._progress.total_sections = len(sections)
        self._progress.status = "running"

        # Process each section sequentially
        for i, section_info in enumerate(sections):
            # Check if cancelled
            if self._cancelled:
                workflow.logger.info("Workflow cancelled by user")
                self._progress.status = "cancelled"
                break

            section_id = section_info.get('id')
            section_title = section_info.get('title', '')

            workflow.logger.info(f"Processing section {i+1}/{len(sections)}: {section_id}")

            # Update progress
            self._progress.current_section = section_title
            await self._send_progress(session_id)

            try:
                # Execute child workflow for section
                section_result = await workflow.execute_child_workflow(
                    SectionAnalysisWorkflow.run,
                    args=[
                        section_id,
                        company_data,
                        configuration,
                        self._accumulated_context
                    ],
                    id=f"{workflow.info().workflow_id}-section-{section_id}",
                    task_queue=workflow.info().task_queue,
                    execution_timeout=timedelta(minutes=10)
                )

                # Accumulate results
                predictions = section_result.get('predictions', {})
                reasoning = section_result.get('reasoning', {})
                rag_metadata = section_result.get('rag_metadata', {})
                updated_context = section_result.get('updated_context', '')

                self._all_predictions.update(predictions)
                self._all_reasoning.update(reasoning)
                self._all_rag_metadata[section_id] = rag_metadata
                self._accumulated_context = updated_context

                # Update progress
                self._progress.sections_completed += 1
                self._progress.predictions_made += len(predictions)

                workflow.logger.info(
                    f"Section {section_id} completed: {len(predictions)} predictions"
                )

            except Exception as e:
                workflow.logger.error(f"Error processing section {section_id}: {str(e)}")
                # Continue to next section (graceful degradation)
                self._progress.sections_completed += 1
                continue

        # Mark as completed
        if not self._cancelled:
            self._progress.status = "completed"

        # Save final results
        await workflow.execute_activity(
            save_questionnaire_results,
            args=[
                session_id,
                self._all_predictions,
                self._all_reasoning,
                self._all_rag_metadata,
                self._accumulated_context
            ],
            start_to_close_timeout=timedelta(seconds=30)
        )

        workflow.logger.info(
            f"Questionnaire analysis completed: {self._progress.predictions_made} predictions "
            f"across {self._progress.sections_completed} sections"
        )

        return {
            "session_id": session_id,
            "total_predictions": self._progress.predictions_made,
            "sections_processed": self._progress.sections_completed,
            "predictions": self._all_predictions,
            "reasoning": self._all_reasoning,
            "rag_metadata": self._all_rag_metadata,
            "final_context": self._accumulated_context,
            "status": self._progress.status
        }

    async def _send_progress(self, session_id: str) -> None:
        """
        Send progress update activity.

        Args:
            session_id: Session identifier
        """
        try:
            await workflow.execute_activity(
                send_progress_update,
                args=[
                    session_id,
                    f"Processing {self._progress.current_section}",
                    self._progress.sections_completed,
                    self._progress.total_sections
                ],
                start_to_close_timeout=timedelta(seconds=5)
            )
        except Exception as e:
            workflow.logger.warning(f"Failed to send progress update: {str(e)}")

    @workflow.signal
    async def cancel_analysis(self) -> None:
        """
        Signal to cancel the analysis.

        This allows users to stop the workflow mid-execution.
        """
        workflow.logger.info("Received cancellation signal")
        self._cancelled = True
        self._progress.status = "cancelled"

    @workflow.query
    def get_current_progress(self) -> Dict[str, Any]:
        """
        Query current progress of analysis.

        Returns:
            Dictionary with progress information
        """
        return {
            "sections_completed": self._progress.sections_completed,
            "total_sections": self._progress.total_sections,
            "predictions_made": self._progress.predictions_made,
            "current_section": self._progress.current_section,
            "status": self._progress.status
        }

    @workflow.query
    def get_section_status(self, section_id: str) -> Dict[str, Any]:
        """
        Query status of specific section.

        Args:
            section_id: Section identifier

        Returns:
            Dictionary with section status
        """
        has_metadata = section_id in self._all_rag_metadata
        section_predictions = {
            k: v for k, v in self._all_predictions.items()
            if k.startswith(section_id.replace('SEC_', ''))
        }

        return {
            "section_id": section_id,
            "processed": has_metadata,
            "predictions_count": len(section_predictions),
            "has_rag_data": has_metadata
        }
