"""
Section Analyzer - Parses and analyzes questionnaire sections.

This module provides functionality to parse Questions.json into sections,
identify root questions, detect section complexity, and calculate optimal RAG parameters.
"""

import json
import logging
from typing import Dict, Any, List, Optional, Set
from pathlib import Path

logger = logging.getLogger(__name__)


class SectionAnalyzer:
    """Analyzes questionnaire sections for batch processing."""

    def __init__(self, questions_json_path: Optional[str] = None):
        """
        Initialize Section Analyzer.

        Args:
            questions_json_path: Path to Questions.json file
        """
        if questions_json_path is None:
            # Default path: qna/Questions.json
            backend_dir = Path(__file__).parent.parent
            questions_json_path = backend_dir.parent / "qna" / "Questions.json"

        self.questions_json_path = Path(questions_json_path)
        self.questions_data = None
        self.sections = None

    def load_questions_json(self) -> Dict[str, Any]:
        """
        Load and parse Questions.json file.

        Returns:
            Parsed JSON data

        Raises:
            FileNotFoundError: If Questions.json not found
            json.JSONDecodeError: If JSON is malformed
        """
        try:
            with open(self.questions_json_path, 'r', encoding='utf-8') as f:
                self.questions_data = json.load(f)
                logger.info(f"Loaded questions from {self.questions_json_path}")
                return self.questions_data
        except FileNotFoundError:
            logger.error(f"Questions.json not found at {self.questions_json_path}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse Questions.json: {str(e)}")
            raise

    def parse_sections(self) -> Dict[str, Dict[str, Any]]:
        """
        Parse Questions.json and extract sections with their questions.

        Section boundaries:
        - Starts with type: "section"
        - Ends when next section starts or at end of array
        - All questions between sections belong to the first section

        Returns:
            Dictionary mapping section_id to section data:
            {
                "SEC_BS": {
                    "id": "SEC_BS",
                    "title": "BUSINESS STRUCTURE",
                    "questions": [question_objects],
                    "root_questions": [question_ids],
                    "complexity": "medium",
                    "optimal_top_k": 15
                }
            }
        """
        if self.questions_data is None:
            self.load_questions_json()

        sections = {}
        current_section = None
        current_section_id = None

        questions_array = self.questions_data.get('questions', [])

        for item in questions_array:
            if item.get('type') == 'section':
                # Save previous section if exists
                if current_section is not None:
                    self._finalize_section(sections, current_section_id, current_section)

                # Start new section
                current_section_id = item['id']
                current_section = {
                    'id': item['id'],
                    'title': item.get('title', ''),
                    'questions': []
                }
            elif current_section is not None:
                # Add question to current section
                current_section['questions'].append(item)

        # Finalize last section
        if current_section is not None:
            self._finalize_section(sections, current_section_id, current_section)

        self.sections = sections
        logger.info(f"Parsed {len(sections)} sections from Questions.json")
        return sections

    def _finalize_section(
        self,
        sections: Dict[str, Dict[str, Any]],
        section_id: str,
        section_data: Dict[str, Any]
    ):
        """
        Finalize section by analyzing complexity and calculating parameters.

        Args:
            sections: Dictionary to add section to
            section_id: Section identifier
            section_data: Section data with questions
        """
        # Find root questions
        root_questions = self.find_root_questions(section_data['questions'])
        section_data['root_questions'] = [q['id'] for q in root_questions]

        # Detect complexity
        complexity = self.detect_section_complexity(section_data['questions'])
        section_data['complexity'] = complexity

        # Calculate optimal top_k
        num_questions = len(section_data['questions'])
        optimal_top_k = self.calculate_optimal_top_k(num_questions, complexity)
        section_data['optimal_top_k'] = optimal_top_k

        sections[section_id] = section_data

    def find_root_questions(self, questions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Find root questions - questions not referenced by any 'next' field.

        Root questions are visible immediately when section starts.
        Revealed questions appear only after answering previous questions.

        Args:
            questions: List of question objects in section

        Returns:
            List of root question objects
        """
        # Collect all question IDs that are referenced in 'next' fields
        referenced_ids: Set[str] = set()

        for question in questions:
            # Check 'next' field at question level (for input type)
            if 'next' in question:
                referenced_ids.update(question['next'])

            # Check 'next' field in options (for single/multi type)
            if 'options' in question:
                for option in question['options']:
                    if 'next' in option:
                        referenced_ids.update(option['next'])

        # Root questions are those NOT referenced anywhere
        root_questions = [
            q for q in questions
            if q['id'] not in referenced_ids
        ]

        logger.debug(f"Found {len(root_questions)} root questions out of {len(questions)} total")
        return root_questions

    def detect_section_complexity(self, questions: List[Dict[str, Any]]) -> str:
        """
        Detect section complexity based on question structure.

        Complexity levels:
        - Low: Simple yes/no questions, no conditionals (<3 questions)
        - Medium: Standard multi-choice, some conditionals (3-6 questions)
        - High: Complex conditional trees, many questions (>6 questions)

        Args:
            questions: List of question objects

        Returns:
            Complexity level: 'low', 'medium', or 'high'
        """
        num_questions = len(questions)

        # Count conditional questions (those with 'next' fields)
        conditional_count = 0
        max_depth = 0

        for question in questions:
            has_next = False

            # Check question-level next
            if 'next' in question:
                has_next = True
                max_depth = max(max_depth, len(question['next']))

            # Check option-level next
            if 'options' in question:
                for option in question['options']:
                    if 'next' in option:
                        has_next = True
                        max_depth = max(max_depth, len(option['next']))

            if has_next:
                conditional_count += 1

        # Calculate complexity
        if num_questions <= 2:
            complexity = 'low'
        elif num_questions <= 6:
            if conditional_count > 3 or max_depth > 3:
                complexity = 'high'
            else:
                complexity = 'medium'
        else:
            if conditional_count > 5 or max_depth > 4:
                complexity = 'high'
            else:
                complexity = 'medium'

        logger.debug(
            f"Section complexity: {complexity} "
            f"(questions={num_questions}, conditionals={conditional_count}, max_depth={max_depth})"
        )
        return complexity

    def calculate_optimal_top_k(
        self,
        num_questions: int,
        complexity: str = "medium"
    ) -> int:
        """
        Calculate optimal top_k for RAG retrieval based on section size and complexity.

        Formula:
        - Base: 3 chunks per question
        - Complexity multipliers:
          - Low: 0.8x (simple questions)
          - Medium: 1.0x (standard questions)
          - High: 1.5x (complex conditional trees)
        - Bounds: min=5, max=20 (RAG API limits)

        Args:
            num_questions: Number of questions in section
            complexity: Section complexity ('low', 'medium', 'high')

        Returns:
            Optimal top_k value

        Examples:
            >>> calculate_optimal_top_k(5, "high")
            20  # Capped at max
            >>> calculate_optimal_top_k(8, "high")
            20  # Capped at max
            >>> calculate_optimal_top_k(3, "low")
            7
        """
        base_k = 3
        multipliers = {
            "low": 0.8,
            "medium": 1.0,
            "high": 1.5
        }

        multiplier = multipliers.get(complexity, 1.0)
        optimal = int(base_k * num_questions * multiplier)

        # Apply bounds (RAG API max is 20)
        bounded = max(5, min(20, optimal))

        logger.debug(
            f"Calculated top_k: {bounded} "
            f"(questions={num_questions}, complexity={complexity}, raw={optimal})"
        )
        return bounded

    def get_section_questions(self, section_id: str) -> List[Dict[str, Any]]:
        """
        Get all questions for a specific section.

        Args:
            section_id: Section identifier (e.g., "SEC_BS")

        Returns:
            List of question objects

        Raises:
            ValueError: If section not found
        """
        if self.sections is None:
            self.parse_sections()

        if section_id not in self.sections:
            raise ValueError(f"Section '{section_id}' not found")

        return self.sections[section_id]['questions']

    def get_section_info(self, section_id: str) -> Dict[str, Any]:
        """
        Get complete section information.

        Args:
            section_id: Section identifier

        Returns:
            Section data including questions, root_questions, complexity, optimal_top_k

        Raises:
            ValueError: If section not found
        """
        if self.sections is None:
            self.parse_sections()

        if section_id not in self.sections:
            raise ValueError(f"Section '{section_id}' not found")

        return self.sections[section_id]

    def get_all_section_ids(self) -> List[str]:
        """
        Get list of all section IDs in order.

        Returns:
            List of section IDs (e.g., ["SEC_BS", "SEC_CL", ...])
        """
        if self.sections is None:
            self.parse_sections()

        return list(self.sections.keys())

    def get_question_by_id(self, question_id: str) -> Optional[Dict[str, Any]]:
        """
        Find a question by ID across all sections.

        Args:
            question_id: Question identifier

        Returns:
            Question object or None if not found
        """
        if self.sections is None:
            self.parse_sections()

        for section in self.sections.values():
            for question in section['questions']:
                if question['id'] == question_id:
                    return question

        return None


# Singleton instance
_section_analyzer_instance: Optional[SectionAnalyzer] = None


def get_section_analyzer() -> SectionAnalyzer:
    """
    Get singleton Section Analyzer instance.

    Returns:
        Shared SectionAnalyzer instance
    """
    global _section_analyzer_instance
    if _section_analyzer_instance is None:
        _section_analyzer_instance = SectionAnalyzer()
    return _section_analyzer_instance
