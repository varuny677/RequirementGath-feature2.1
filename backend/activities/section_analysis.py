"""
Section analysis activities for Temporal workflows.

This module contains all activities for section-based questionnaire processing:
- Section structure parsing
- RAG chunk retrieval for sections
- Batch question prediction
- Dynamic question resolution
- Context generation
- Progress tracking
- Results persistence
"""

import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from temporalio import activity
import google.generativeai as genai

from config import settings
from services.section_analyzer import get_section_analyzer
from services.rag_client import get_rag_client
from services.dynamic_question_resolver import create_resolver_for_section
from services.prediction_context import get_or_create_context
from services.firestore_service import get_firestore_service


@activity.defn
async def parse_section_structure(section_id: str) -> Dict[str, Any]:
    """
    Parse section structure from Questions.json.

    Args:
        section_id: Section identifier (e.g., "SEC_BS")

    Returns:
        Dictionary containing:
            - section_id: Section identifier
            - title: Section title
            - all_questions: All questions in section
            - root_questions: Questions with no dependencies
            - complexity: Section complexity (low/medium/high)
            - optimal_top_k: Optimal RAG retrieval parameter
    """
    activity.logger.info(f"Parsing structure for section {section_id}")

    try:
        analyzer = get_section_analyzer()
        section_info = analyzer.get_section_info(section_id)

        # Extract root questions from IDs
        root_question_ids = section_info.get('root_questions', [])
        root_questions = [
            q for q in section_info['questions']
            if q['id'] in root_question_ids
        ]

        result = {
            "section_id": section_id,
            "title": section_info['title'],
            "all_questions": section_info['questions'],
            "root_questions": root_questions,
            "complexity": section_info.get('complexity', 'medium'),
            "optimal_top_k": section_info.get('optimal_top_k', 15)
        }

        activity.logger.info(
            f"Section {section_id}: {len(result['all_questions'])} questions, "
            f"{len(root_questions)} root, complexity={result['complexity']}"
        )

        return result

    except Exception as e:
        activity.logger.error(f"Error parsing section {section_id}: {str(e)}")
        raise


@activity.defn
async def retrieve_section_chunks(
    section_title: str,
    questions: List[Dict[str, Any]],
    company_data: Dict[str, Any],
    configuration: Dict[str, Any],
    previous_context: str,
    top_k: int = 15
) -> Dict[str, Any]:
    """
    Retrieve RAG chunks for entire section (ONE CALL).

    Args:
        section_title: Section title
        questions: All questions in section
        company_data: Company information
        configuration: Configuration settings
        previous_context: Context from previous sections
        top_k: Number of chunks to retrieve

    Returns:
        Dictionary containing:
            - success: Whether retrieval succeeded
            - chunks: List of retrieved chunks
            - sources: List of source document names
            - retrieval_time: Time taken in seconds
            - section_query: Query used
            - error: Error message if failed
    """
    activity.logger.info(
        f"Retrieving {top_k} chunks for section '{section_title}' "
        f"with {len(questions)} questions"
    )

    try:
        rag_client = get_rag_client()

        # Check if RAG is healthy
        if not rag_client.check_health(timeout=3):
            activity.logger.warning("RAG API unhealthy, skipping retrieval")
            return {
                "success": False,
                "chunks": [],
                "sources": [],
                "error": "RAG API unhealthy"
            }

        # Retrieve chunks for section
        result = rag_client.retrieve_chunks_for_section(
            section_title=section_title,
            questions=questions,
            company_data=company_data,
            configuration=configuration,
            previous_context=previous_context,
            top_k=top_k,
            timeout=30
        )

        if result.get('success'):
            chunks = result.get('chunks', [])
            sources = rag_client.extract_sources(chunks)

            activity.logger.info(
                f"Retrieved {len(chunks)} chunks from {len(sources)} sources "
                f"in {result.get('retrieval_time', 0):.2f}s"
            )

            return {
                "success": True,
                "chunks": chunks,
                "sources": sources,
                "retrieval_time": result.get('retrieval_time', 0),
                "section_query": result.get('section_query', ''),
                "total_chunks": len(chunks)
            }
        else:
            activity.logger.warning(f"RAG retrieval failed: {result.get('error')}")
            return {
                "success": False,
                "chunks": [],
                "sources": [],
                "error": result.get('error', 'Unknown error')
            }

    except Exception as e:
        activity.logger.error(f"Error retrieving chunks: {str(e)}")
        return {
            "success": False,
            "chunks": [],
            "sources": [],
            "error": str(e)
        }


@activity.defn
async def predict_question_batch_with_rag(
    questions: List[Dict[str, Any]],
    rag_chunks: List[Dict[str, Any]],
    company_data: Dict[str, Any],
    configuration: Dict[str, Any],
    previous_context: str,
    previous_predictions: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Predict answers for multiple questions using cached RAG chunks.

    Args:
        questions: List of question objects to predict
        rag_chunks: Pre-retrieved RAG chunks (CACHED)
        company_data: Company information
        configuration: Configuration settings
        previous_context: Context from previous sections
        previous_predictions: Predictions made earlier in this section

    Returns:
        Dictionary containing:
            - predictions: Dict mapping question_id to answer
            - reasoning: Dict mapping question_id to reasoning
            - confidence: Dict mapping question_id to confidence level
    """
    activity.logger.info(f"Predicting batch of {len(questions)} questions")

    try:
        # Configure Gemini
        genai.configure(api_key=settings.google_api_key)
        model = genai.GenerativeModel(model_name=settings.gemini_model)

        # Build batch prediction prompt
        prompt = _build_batch_prediction_prompt(
            questions=questions,
            rag_chunks=rag_chunks,
            company_data=company_data,
            previous_context=previous_context,
            previous_predictions=previous_predictions,
            configuration=configuration
        )

        # Generate predictions
        generation_config = {
            'temperature': 0.3,  # Lower temperature for more consistent predictions
            'top_p': 0.95,
            'max_output_tokens': 4096,
        }

        response = model.generate_content(
            prompt,
            generation_config=generation_config
        )

        activity.logger.info("LLM response received for batch prediction")

        # Parse response
        result = _parse_batch_prediction_response(response.text, questions)

        activity.logger.info(
            f"Parsed {len(result['predictions'])} predictions from LLM response"
        )

        return result

    except Exception as e:
        activity.logger.error(f"Error in batch prediction: {str(e)}")
        # Return empty predictions on error
        return {
            "predictions": {},
            "reasoning": {},
            "confidence": {},
            "error": str(e)
        }


def _build_batch_prediction_prompt(
    questions: List[Dict[str, Any]],
    rag_chunks: List[Dict[str, Any]],
    company_data: Dict[str, Any],
    previous_context: str,
    previous_predictions: Dict[str, Any],
    configuration: Dict[str, Any] = None
) -> str:
    """Build comprehensive prompt for batch prediction."""

    # Extract company information from company_data
    # The company_data has structure: {"Company name": "...", "Sector": "...", ...}
    company_name = company_data.get('Company name', 'Unknown')

    # company_data is already the flat object with all fields
    company_info = company_data

    # Extract fields from nested structure (with actual field names from Gemini)
    sector = company_info.get('Sector', 'Unknown')
    sub_sector = company_info.get('Sub Sector', '')
    company_description = company_info.get('brief about company', '')
    company_size = company_info.get('No of Employees', '')
    revenue = company_info.get('Networth', '')
    country_of_origin = company_info.get('Country of origin', '')
    global_presence = company_info.get('Global presence', '')
    operating_countries = company_info.get('List of countries they operate in', [])
    compliance_requirements = company_info.get('Compliance Requirements', [])

    # Cloud provider from configuration (not in company data)
    cloud_provider = configuration.get('cloud_provider', 'AWS') if configuration else 'AWS'

    # Log extracted company data for debugging
    activity.logger.info(
        f"Company data extracted - Name: {company_name}, Sector: {sector}, "
        f"Sub-Sector: {sub_sector}, Country: {country_of_origin}, "
        f"Cloud: {cloud_provider}"
    )

    # Format RAG context
    rag_context = ""
    if rag_chunks:
        rag_client = get_rag_client()
        rag_context = rag_client.format_chunks_as_context(
            rag_chunks,
            include_sources=True,
            include_similarity=False
        )

    # Format questions
    questions_list = []
    for i, question in enumerate(questions, 1):
        qid = question['id']
        qtext = question['question']
        qtype = question.get('type', 'single')
        options = question.get('options', [])

        question_str = f"{i}. [{qid}] {qtext}\n   Type: {qtype}"
        if options:
            option_labels = [f"   - {opt.get('label')}" for opt in options[:10]]
            question_str += "\n" + "\n".join(option_labels)
            if len(options) > 10:
                question_str += f"\n   ... and {len(options) - 10} more options"

        questions_list.append(question_str)

    questions_section = "\n\n".join(questions_list)

    # Format previous predictions in section
    prev_predictions_str = ""
    if previous_predictions:
        prev_list = []
        for qid, answer in previous_predictions.items():
            if isinstance(answer, list):
                answer_str = ", ".join(str(a) for a in answer)
            else:
                answer_str = str(answer)
            prev_list.append(f"- {qid}: {answer_str}")
        prev_predictions_str = "\n".join(prev_list)

    # Format configuration data
    config_str = ""
    if configuration:
        config_parts = []
        if configuration.get('sub_sector'):
            config_parts.append(f"- Sub-Sector: {configuration['sub_sector']}")
        if configuration.get('compliance_standards'):
            standards = configuration['compliance_standards']
            if isinstance(standards, list):
                config_parts.append(f"- Compliance Standards: {', '.join(standards)}")
            else:
                config_parts.append(f"- Compliance Standards: {standards}")
        if configuration.get('environments'):
            envs = configuration['environments']
            if isinstance(envs, list):
                config_parts.append(f"- Environments: {', '.join(envs)}")
            else:
                config_parts.append(f"- Environments: {envs}")
        if configuration.get('business_units'):
            bus = configuration['business_units']
            if isinstance(bus, list):
                config_parts.append(f"- Business Units: {', '.join(str(b) for b in bus)}")
            else:
                config_parts.append(f"- Business Units: {bus}")
        if configuration.get('regions'):
            regions = configuration['regions']
            if isinstance(regions, list):
                config_parts.append(f"- Regions: {', '.join(regions)}")
            else:
                config_parts.append(f"- Regions: {regions}")
        if configuration.get('data_residency_requirements'):
            config_parts.append(f"- Data Residency: {configuration['data_residency_requirements']}")

        if config_parts:
            config_str = "\n".join(config_parts)

    # Build company info section with comprehensive details
    company_info_parts = [
        f"- Name: {company_name}",
        f"- Sector: {sector}",
        f"- Cloud Provider: {cloud_provider}"
    ]
    if sub_sector:
        company_info_parts.append(f"- Sub-Sector: {sub_sector}")
    if company_description:
        company_info_parts.append(f"- Description: {company_description}")
    if country_of_origin:
        company_info_parts.append(f"- Country of Origin: {country_of_origin}")
    if company_size:
        company_info_parts.append(f"- Size: {company_size}")
    if revenue:
        company_info_parts.append(f"- Revenue: {revenue}")
    if global_presence:
        company_info_parts.append(f"- Global Presence: {global_presence}")
    if operating_countries:
        if isinstance(operating_countries, list):
            countries_str = ", ".join(str(c) for c in operating_countries[:10])
            if len(operating_countries) > 10:
                countries_str += f" (and {len(operating_countries) - 10} more)"
            company_info_parts.append(f"- Operating Countries: {countries_str}")
    if compliance_requirements:
        if isinstance(compliance_requirements, list):
            comp_str = ", ".join(str(c) for c in compliance_requirements)
            company_info_parts.append(f"- Industry Compliance: {comp_str}")

    company_info_section = "\n".join(company_info_parts)

    # Build prompt
    prompt = f"""You are an expert {cloud_provider} cloud architect analyzing requirements for a Landing Zone design.

Company Information:
{company_info_section}

User Configuration (From intake form):
{config_str if config_str else 'None provided'}

Previous Context:
{previous_context if previous_context else 'None'}

Previous Predictions in Current Section:
{prev_predictions_str if prev_predictions_str else 'None'}

Reference Documentation:
{rag_context if rag_context else 'No documentation available - use best practices knowledge'}

Questions to Answer:
{questions_section}

Instructions:
1. For EACH question, predict the most appropriate answer based on:
   - Company information (sector, size, typical needs)
   - Reference documentation provided above
   - {cloud_provider} best practices
   - Previous context and predictions

2. For single-choice questions: Select ONE option that best fits
3. For multi-choice questions: Select ALL relevant options (return as list)
4. For input questions: Provide a reasonable value/text

5. Provide reasoning for EACH prediction explaining why this choice makes sense

6. Return your response in this EXACT JSON format:
{{
  "predictions": {{
    "QUESTION_ID": "answer" or ["answer1", "answer2"],
    ...
  }},
  "reasoning": {{
    "QUESTION_ID": "Explanation for this choice based on company context and best practices",
    ...
  }},
  "confidence": {{
    "QUESTION_ID": "high" or "medium" or "low",
    ...
  }}
}}

IMPORTANT:
- Return ONLY valid JSON, no markdown code blocks
- Include ALL question IDs in your response
- Use exact option labels from the questions
- Be consistent with {cloud_provider} best practices
"""

    return prompt


def _parse_batch_prediction_response(
    response_text: str,
    questions: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """Parse LLM response for batch predictions."""

    try:
        # Clean response (remove markdown code blocks if present)
        cleaned_text = response_text.strip()
        if cleaned_text.startswith('```'):
            # Remove markdown code block markers
            lines = cleaned_text.split('\n')
            lines = [l for l in lines if not l.strip().startswith('```')]
            cleaned_text = '\n'.join(lines)

        # Parse JSON
        result = json.loads(cleaned_text)

        predictions = result.get('predictions', {})
        reasoning = result.get('reasoning', {})
        confidence = result.get('confidence', {})

        # Ensure all questions have predictions
        for question in questions:
            qid = question['id']
            if qid not in predictions:
                # Fallback: Use first option or empty string
                options = question.get('options', [])
                if options:
                    predictions[qid] = options[0].get('label', '')
                else:
                    predictions[qid] = ''
                reasoning[qid] = 'Default answer - LLM did not provide prediction'
                confidence[qid] = 'low'

        return {
            "predictions": predictions,
            "reasoning": reasoning,
            "confidence": confidence
        }

    except json.JSONDecodeError as e:
        activity.logger.error(f"Failed to parse JSON response: {str(e)}")
        activity.logger.debug(f"Response text: {response_text[:500]}")

        # Fallback: Return default answers
        predictions = {}
        reasoning = {}
        confidence = {}

        for question in questions:
            qid = question['id']
            options = question.get('options', [])
            if options:
                predictions[qid] = options[0].get('label', '')
            else:
                predictions[qid] = ''
            reasoning[qid] = 'Error parsing LLM response - using default'
            confidence[qid] = 'low'

        return {
            "predictions": predictions,
            "reasoning": reasoning,
            "confidence": confidence,
            "error": f"JSON parse error: {str(e)}"
        }


@activity.defn
async def resolve_next_questions(
    current_questions: List[Dict[str, Any]],
    predictions: Dict[str, Any],
    all_section_questions: List[Dict[str, Any]]
) -> List[str]:
    """
    Determine which questions should be revealed next.

    Args:
        current_questions: Questions that were just answered
        predictions: Predictions for current questions
        all_section_questions: All questions in section

    Returns:
        List of question IDs to reveal in next wave
    """
    activity.logger.info(
        f"Resolving next questions for {len(current_questions)} predictions"
    )

    try:
        resolver = create_resolver_for_section(all_section_questions)

        # Process all predictions to find next questions
        next_question_ids = resolver.process_wave(predictions)

        activity.logger.info(f"Revealed {len(next_question_ids)} next questions")

        return next_question_ids

    except Exception as e:
        activity.logger.error(f"Error resolving next questions: {str(e)}")
        return []


@activity.defn
async def generate_section_context(
    section_id: str,
    section_title: str,
    predictions: Dict[str, Any],
    reasoning: Dict[str, str],
    previous_context: str,
    all_section_questions: List[Dict[str, Any]] = None
) -> str:
    """
    Generate updated context summary for next section with question text and reasoning.

    Args:
        section_id: Section identifier
        section_title: Section title
        predictions: Section predictions
        reasoning: Section reasoning
        previous_context: Context from previous sections
        all_section_questions: List of all question objects in this section (optional)

    Returns:
        Updated context string with format: "Q_ID: Question text → Answer"
    """
    activity.logger.info(f"Generating enhanced context for section {section_id}")

    try:
        # Build question ID to question text mapping
        question_text_map = {}
        if all_section_questions:
            for q in all_section_questions:
                question_text_map[q['id']] = q.get('question', '')

        context_parts = []

        # Add current section
        context_parts.append(f"[Section: {section_title}]")

        for qid, answer in predictions.items():
            # Format answer
            if isinstance(answer, list):
                answer_str = ", ".join(str(a) for a in answer)
            else:
                answer_str = str(answer)

            # Get question text if available
            question_text = question_text_map.get(qid, '')

            if question_text:
                # Enhanced format: "Q_ID: Question text → Answer"
                context_parts.append(f"- {qid}: {question_text} → {answer_str}")
            else:
                # Fallback to old format if question text not available
                context_parts.append(f"- {qid}: {answer_str}")

            # Add condensed reasoning (max 150 characters)
            reason = reasoning.get(qid, '')
            if reason:
                condensed_reasoning = reason[:150] + "..." if len(reason) > 150 else reason
                context_parts.append(f"  (Reasoning: {condensed_reasoning})")

        current_section_context = "\n".join(context_parts)

        # Combine with previous context (keep limited to last 2000 chars for better context)
        if previous_context:
            # Limit previous context to ~2000 chars to maintain more history
            limited_previous = previous_context[-2000:] if len(previous_context) > 2000 else previous_context
            full_context = f"{limited_previous}\n\n{current_section_context}"
        else:
            full_context = current_section_context

        activity.logger.info(f"Generated enhanced context: {len(full_context)} characters")

        return full_context

    except Exception as e:
        activity.logger.error(f"Error generating context: {str(e)}")
        return previous_context  # Return previous context on error


@activity.defn
async def send_progress_update(
    session_id: str,
    message: str,
    current: int,
    total: int
) -> None:
    """
    Send progress update to Firestore for frontend polling.

    Args:
        session_id: Session identifier
        message: Progress message
        current: Current progress value
        total: Total progress value
    """
    activity.logger.info(f"Progress update for {session_id}: {current}/{total} - {message}")

    try:
        firestore = get_firestore_service()

        progress_data = {
            "message": message,
            "current": current,
            "total": total,
            "percentage": int((current / total) * 100) if total > 0 else 0,
            "timestamp": datetime.now().isoformat()
        }

        # Update in Firestore (use set with merge to create if doesn't exist)
        firestore.db.collection("sessions").document(session_id).set(
            {"questionnaire_progress": progress_data},
            merge=True
        )

        activity.logger.info(f"Progress update sent: {progress_data['percentage']}%")

    except Exception as e:
        activity.logger.error(f"Error sending progress update: {str(e)}")
        # Don't raise - progress updates are non-critical


@activity.defn
async def save_questionnaire_results(
    session_id: str,
    predictions: Dict[str, Any],
    reasoning: Dict[str, str],
    rag_metadata: Dict[str, Any],
    final_context: str
) -> None:
    """
    Save complete questionnaire results to Firestore.

    Args:
        session_id: Session identifier
        predictions: All predictions
        reasoning: All reasoning
        rag_metadata: RAG metadata by section
        final_context: Final accumulated context
    """
    activity.logger.info(
        f"Saving results for session {session_id}: {len(predictions)} predictions"
    )

    try:
        firestore = get_firestore_service()

        # Prepare results data
        results_data = {
            "questionnaire_results": {
                "predictions": predictions,
                "reasoning": reasoning,
                "rag_metadata": rag_metadata,
                "final_context": final_context,
                "total_predictions": len(predictions),
                "completed_at": datetime.now().isoformat()
            },
            "questionnaire_status": "completed",
            "updated_at": datetime.now().isoformat()
        }

        # Save to Firestore (use set with merge to create if doesn't exist)
        firestore.db.collection("sessions").document(session_id).set(results_data, merge=True)

        activity.logger.info(f"Results saved successfully for session {session_id}")

    except Exception as e:
        activity.logger.error(f"Error saving results: {str(e)}")
        raise
