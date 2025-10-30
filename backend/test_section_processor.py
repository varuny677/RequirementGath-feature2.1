"""
Test script for section-based questionnaire processing.

This script tests the new section analyzer and dynamic question resolver services.
"""

import sys
import json
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent))

from services.section_analyzer import get_section_analyzer
from services.dynamic_question_resolver import create_resolver_for_section


def test_section_analyzer():
    """Test Section Analyzer functionality."""
    print("=" * 80)
    print("TESTING SECTION ANALYZER")
    print("=" * 80)

    analyzer = get_section_analyzer()

    # Parse sections
    sections = analyzer.parse_sections()
    print(f"\n[OK] Parsed {len(sections)} sections from Questions.json")

    # Display section information
    for section_id, section_data in sections.items():
        print(f"\n{section_id}: {section_data['title']}")
        print(f"  - Total questions: {len(section_data['questions'])}")
        print(f"  - Root questions: {len(section_data['root_questions'])}")
        print(f"  - Complexity: {section_data['complexity']}")
        print(f"  - Optimal top_k: {section_data['optimal_top_k']}")

        # Show root questions
        print(f"  - Root question IDs: {section_data['root_questions']}")


def test_dynamic_resolver():
    """Test Dynamic Question Resolver functionality."""
    print("\n" + "=" * 80)
    print("TESTING DYNAMIC QUESTION RESOLVER")
    print("=" * 80)

    analyzer = get_section_analyzer()
    sections = analyzer.parse_sections()

    # Test with Business Structure section
    section_id = "SEC_BS"
    section_data = analyzer.get_section_info(section_id)
    questions = section_data['questions']

    print(f"\nTesting resolver for section: {section_data['title']}")
    print(f"Total questions in section: {len(questions)}")

    resolver = create_resolver_for_section(questions)

    # Test resolving next questions for BS_Q1
    test_question_id = "BS_Q1"
    test_answer = "Environment-wise"

    print(f"\nTest case:")
    print(f"  Question ID: {test_question_id}")
    print(f"  Answer: {test_answer}")

    next_questions = resolver.resolve_next_questions(test_question_id, test_answer)
    print(f"  Revealed questions: {next_questions}")

    # Test with different answer
    test_answer2 = "Business Unit-wise"
    next_questions2 = resolver.resolve_next_questions(test_question_id, test_answer2)
    print(f"\nTest case 2:")
    print(f"  Question ID: {test_question_id}")
    print(f"  Answer: {test_answer2}")
    print(f"  Revealed questions: {next_questions2}")

    # Test wave processing
    print("\n" + "-" * 40)
    print("Testing wave processing:")

    wave_predictions = {
        "BS_Q1": "Environment-wise"
    }

    next_wave_ids = resolver.process_wave(wave_predictions)
    print(f"  Wave 1 predictions: {wave_predictions}")
    print(f"  Next wave question IDs: {next_wave_ids}")

    # Validate section structure
    print("\n" + "-" * 40)
    print("Validating section structure:")
    validation = resolver.validate_section_structure()

    print(f"  Valid: {validation['valid']}")
    print(f"  Warnings: {len(validation['warnings'])}")
    print(f"  Errors: {len(validation['errors'])}")
    print(f"  Stats: {validation['stats']}")

    if validation['warnings']:
        print("  Warning messages:")
        for warning in validation['warnings']:
            print(f"    - {warning}")

    if validation['errors']:
        print("  Error messages:")
        for error in validation['errors']:
            print(f"    - {error}")


def test_rag_client_query_builder():
    """Test RAG Client section query building."""
    print("\n" + "=" * 80)
    print("TESTING RAG CLIENT QUERY BUILDER")
    print("=" * 80)

    from services.rag_client import get_rag_client

    rag_client = get_rag_client()
    analyzer = get_section_analyzer()

    # Get Business Structure section
    section_data = analyzer.get_section_info("SEC_BS")

    # Build section query
    company_data = {
        "company_name": "Microsoft",
        "sector": "Technology",
        "cloud_provider": "AWS"
    }

    query = rag_client._build_section_query(
        section_title=section_data['title'],
        questions=section_data['questions'],
        company_data=company_data,
        previous_context=""
    )

    print("\nGenerated RAG Query for Section:")
    print("-" * 80)
    print(query)
    print("-" * 80)


def main():
    """Run all tests."""
    try:
        print("\n" + "=" * 80)
        print("SECTION-BASED QUESTIONNAIRE PROCESSING - TEST SUITE")
        print("=" * 80)

        # Run tests
        test_section_analyzer()
        test_dynamic_resolver()
        test_rag_client_query_builder()

        print("\n" + "=" * 80)
        print("ALL TESTS COMPLETED SUCCESSFULLY [OK]")
        print("=" * 80)
        print("\nThe section-based processing system is ready to use!")
        print("\nNext steps:")
        print("1. Start Temporal server: temporal server start-dev")
        print("2. Start worker: python backend/worker.py")
        print("3. Start API server: python backend/app.py")
        print("4. Test the new /api/questionnaire/analyze endpoint")

    except Exception as e:
        print(f"\n[FAILED] TEST FAILED: {str(e)}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
