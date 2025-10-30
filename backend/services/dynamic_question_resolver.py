"""
Dynamic Question Resolver - Handles conditional question logic and wave-based processing.

This module resolves which questions should be revealed based on previous answers,
enabling wave-based batch processing of sections with conditional logic.
"""

import logging
from typing import Dict, Any, List, Optional, Set

logger = logging.getLogger(__name__)


class DynamicQuestionResolver:
    """Resolves dynamic questions based on conditional logic."""

    def __init__(self, all_section_questions: List[Dict[str, Any]]):
        """
        Initialize Dynamic Question Resolver.

        Args:
            all_section_questions: All questions in the current section
        """
        self.all_questions = all_section_questions
        self.questions_by_id = {q['id']: q for q in all_section_questions}

    def resolve_next_questions(
        self,
        question_id: str,
        answer: Any
    ) -> List[str]:
        """
        Determine which questions should be revealed based on answer.

        Args:
            question_id: Question that was answered
            answer: The answer given (can be string, list, dict, etc.)

        Returns:
            List of next question IDs to reveal

        Examples:
            >>> resolver.resolve_next_questions("BS_Q1", "Environment-wise")
            ["BS_Q1_ENV"]

            >>> resolver.resolve_next_questions("CL_Q1", "Yes")
            ["CL_Q1_A", "CL_Q1_B", "CL_Q1_C"]
        """
        question = self.questions_by_id.get(question_id)
        if not question:
            logger.warning(f"Question '{question_id}' not found")
            return []

        next_question_ids: List[str] = []

        # Case 1: Question has direct 'next' field (input type)
        if 'next' in question:
            next_question_ids.extend(question['next'])
            logger.debug(f"Question {question_id} has direct next: {question['next']}")

        # Case 2: Question has options with conditional 'next' (single/multi type)
        if 'options' in question:
            next_question_ids.extend(
                self._resolve_option_based_next(question, answer)
            )

        # Remove duplicates while preserving order
        unique_next = list(dict.fromkeys(next_question_ids))

        logger.debug(f"Question {question_id} with answer '{answer}' reveals: {unique_next}")
        return unique_next

    def _resolve_option_based_next(
        self,
        question: Dict[str, Any],
        answer: Any
    ) -> List[str]:
        """
        Resolve next questions based on option selection.

        Args:
            question: Question object with options
            answer: Selected answer(s)

        Returns:
            List of next question IDs
        """
        next_ids: List[str] = []
        question_type = question.get('type', 'single')

        if question_type == 'single':
            # Single choice - answer is a string
            next_ids = self._resolve_single_choice(question, answer)
        elif question_type == 'multi':
            # Multi choice - answer is a list
            next_ids = self._resolve_multi_choice(question, answer)

        return next_ids

    def _resolve_single_choice(
        self,
        question: Dict[str, Any],
        answer: str
    ) -> List[str]:
        """
        Resolve next questions for single-choice answer.

        Args:
            question: Question object
            answer: Selected option label

        Returns:
            List of next question IDs
        """
        if not isinstance(answer, str):
            # Handle case where answer is a dict with 'value' key
            if isinstance(answer, dict) and 'value' in answer:
                answer = answer['value']
            else:
                logger.warning(f"Invalid answer type for single choice: {type(answer)}")
                return []

        options = question.get('options', [])
        for option in options:
            if option.get('label') == answer:
                if 'next' in option:
                    logger.debug(f"Matched option '{answer}' -> next: {option['next']}")
                    return option['next']
                break

        return []

    def _resolve_multi_choice(
        self,
        question: Dict[str, Any],
        answer: Any
    ) -> List[str]:
        """
        Resolve next questions for multi-choice answer.

        Args:
            question: Question object
            answer: List of selected option labels

        Returns:
            List of next question IDs
        """
        # Normalize answer to list
        if isinstance(answer, str):
            selected_labels = [answer]
        elif isinstance(answer, list):
            selected_labels = answer
        else:
            logger.warning(f"Invalid answer type for multi choice: {type(answer)}")
            return []

        next_ids: List[str] = []
        options = question.get('options', [])

        for option in options:
            option_label = option.get('label')
            if option_label in selected_labels:
                if 'next' in option:
                    next_ids.extend(option['next'])
                    logger.debug(f"Matched option '{option_label}' -> next: {option['next']}")

        return next_ids

    def get_questions_by_ids(self, question_ids: List[str]) -> List[Dict[str, Any]]:
        """
        Convert question IDs to full question objects.

        Args:
            question_ids: List of question identifiers

        Returns:
            List of question objects
        """
        questions = []
        for qid in question_ids:
            if qid in self.questions_by_id:
                questions.append(self.questions_by_id[qid])
            else:
                logger.warning(f"Question '{qid}' not found in section")

        return questions

    def process_wave(
        self,
        wave_predictions: Dict[str, Any]
    ) -> List[str]:
        """
        Process a wave of predictions and determine next wave questions.

        Args:
            wave_predictions: Dictionary mapping question_id to answer

        Returns:
            List of question IDs for next wave
        """
        next_wave_ids: Set[str] = set()

        for question_id, answer in wave_predictions.items():
            revealed = self.resolve_next_questions(question_id, answer)
            next_wave_ids.update(revealed)

        next_wave_list = list(next_wave_ids)
        logger.info(f"Wave processing: {len(wave_predictions)} predictions -> {len(next_wave_list)} next questions")
        return next_wave_list

    def build_dependency_tree(self) -> Dict[str, List[str]]:
        """
        Build a dependency tree showing which questions lead to which.

        Returns:
            Dictionary mapping question_id to list of questions it can reveal
        """
        dependency_tree: Dict[str, List[str]] = {}

        for question in self.all_questions:
            qid = question['id']
            next_ids: List[str] = []

            # Direct next
            if 'next' in question:
                next_ids.extend(question['next'])

            # Option-based next
            if 'options' in question:
                for option in question['options']:
                    if 'next' in option:
                        next_ids.extend(option['next'])

            # Remove duplicates
            dependency_tree[qid] = list(dict.fromkeys(next_ids))

        return dependency_tree

    def get_max_wave_depth(self) -> int:
        """
        Calculate maximum wave depth for section (for timeout/limit purposes).

        Returns:
            Maximum number of waves possible
        """
        dependency_tree = self.build_dependency_tree()

        # Use BFS to find longest path
        max_depth = 0
        visited: Set[str] = set()

        def dfs(qid: str, depth: int):
            nonlocal max_depth
            if qid in visited:
                return  # Avoid cycles
            visited.add(qid)

            max_depth = max(max_depth, depth)

            for next_qid in dependency_tree.get(qid, []):
                dfs(next_qid, depth + 1)

            visited.remove(qid)

        # Start from all questions
        for qid in dependency_tree:
            dfs(qid, 1)

        logger.debug(f"Maximum wave depth: {max_depth}")
        return max_depth

    def validate_section_structure(self) -> Dict[str, Any]:
        """
        Validate section structure for potential issues.

        Returns:
            Dictionary with validation results:
            {
                "valid": bool,
                "warnings": List[str],
                "errors": List[str],
                "stats": Dict
            }
        """
        warnings: List[str] = []
        errors: List[str] = []

        # Check for circular dependencies
        dependency_tree = self.build_dependency_tree()
        visited: Set[str] = set()
        rec_stack: Set[str] = set()

        def has_cycle(qid: str) -> bool:
            visited.add(qid)
            rec_stack.add(qid)

            for next_qid in dependency_tree.get(qid, []):
                if next_qid not in visited:
                    if has_cycle(next_qid):
                        return True
                elif next_qid in rec_stack:
                    return True

            rec_stack.remove(qid)
            return False

        # Check all questions for cycles
        for qid in dependency_tree:
            if qid not in visited:
                if has_cycle(qid):
                    errors.append(f"Circular dependency detected involving question '{qid}'")

        # Check for orphaned questions
        referenced_ids = set()
        for next_ids in dependency_tree.values():
            referenced_ids.update(next_ids)

        for question in self.all_questions:
            qid = question['id']
            # If question is referenced but doesn't exist
            if qid in dependency_tree:
                for next_qid in dependency_tree[qid]:
                    if next_qid not in self.questions_by_id:
                        warnings.append(f"Question '{qid}' references non-existent question '{next_qid}'")

        # Statistics
        total_questions = len(self.all_questions)
        questions_with_next = len([q for q in self.all_questions if 'next' in q or any('next' in opt for opt in q.get('options', []))])
        max_depth = self.get_max_wave_depth()

        return {
            "valid": len(errors) == 0,
            "warnings": warnings,
            "errors": errors,
            "stats": {
                "total_questions": total_questions,
                "questions_with_conditionals": questions_with_next,
                "max_wave_depth": max_depth
            }
        }


def create_resolver_for_section(section_questions: List[Dict[str, Any]]) -> DynamicQuestionResolver:
    """
    Factory function to create a resolver for a section.

    Args:
        section_questions: All questions in section

    Returns:
        DynamicQuestionResolver instance
    """
    return DynamicQuestionResolver(section_questions)
