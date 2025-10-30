"""
FastAPI server for the requirement gathering application.

This module provides REST API endpoints and manages Temporal workflow execution.
"""

import logging
import uuid
import os
import datetime
from typing import Dict, Any, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from temporalio.client import Client

from config import settings
from workflows import CompanySearchWorkflow, CompanyDetailWorkflow, QuestionnaireAnalysisWorkflow
from services import FirestoreService, get_or_create_context
from services.section_analyzer import get_section_analyzer
from activities import (
    infer_presumptive_config,
    infer_questionnaire_answers,
    predict_single_question_with_rag
)
import json
import asyncio


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Requirement Gathering API",
    description="API for searching companies using Google ADK and Gemini",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Temporal client (will be initialized on startup)
temporal_client: Client = None

# Firestore service (will be initialized on startup)
firestore_service: FirestoreService = None


class SearchRequest(BaseModel):
    """Request model for company search."""

    query: str
    session_id: Optional[str] = None


class SearchResponse(BaseModel):
    """Response model for company search."""

    session_id: str
    message_id: str
    query: str
    results: Dict[str, Any]


class ChatMessage(BaseModel):
    """Chat message model."""

    id: str
    role: str  # 'user' or 'assistant'
    content: str
    timestamp: str


class SessionResponse(BaseModel):
    """Session response model."""

    session_id: str
    messages: List[Dict[str, Any]]


class ConfigRequest(BaseModel):
    """Request model for generating presumptive configuration."""

    company_data: Dict[str, Any]


class ConfigSaveRequest(BaseModel):
    """Request model for saving configuration."""

    session_id: str
    configuration: Dict[str, Any]


class ConfigResponse(BaseModel):
    """Response model for configuration."""

    success: bool
    data: Dict[str, Any]
    session_id: Optional[str] = None


class QuestionnairePredictRequest(BaseModel):
    """Request model for questionnaire answer prediction."""

    session_id: str
    question_ids: List[str]
    company_data: Dict[str, Any]
    configuration: Dict[str, Any]
    current_answers: Dict[str, Any]


class QuestionnaireSaveRequest(BaseModel):
    """Request model for saving questionnaire progress."""

    session_id: str
    answers: Dict[str, Any]
    ai_predictions: Optional[Dict[str, Any]] = None
    ai_assumptions: Optional[Dict[str, Any]] = None


class QuestionnaireSubmitRequest(BaseModel):
    """Request model for submitting completed questionnaire."""

    session_id: str
    answers: Dict[str, Any]
    company_data: Dict[str, Any]
    configuration: Dict[str, Any]


class SingleQuestionPredictRequest(BaseModel):
    """Request model for predicting a single question with RAG."""

    session_id: str
    question_id: str
    company_data: Dict[str, Any]
    configuration: Dict[str, Any]


class AnalysisRequest(BaseModel):
    """Request model for starting questionnaire analysis workflow."""

    session_id: str
    company_data: Dict[str, Any]
    configuration: Dict[str, Any]


@app.on_event("startup")
async def startup_event() -> None:
    """Initialize Temporal client and Firestore on startup."""
    global temporal_client, firestore_service

    # Initialize Temporal
    logger.info(f"Connecting to Temporal at {settings.temporal_host}")
    try:
        temporal_client = await Client.connect(
            settings.temporal_host,
            namespace=settings.temporal_namespace,
        )
        logger.info("Successfully connected to Temporal server")
    except Exception as e:
        logger.error(f"Failed to connect to Temporal: {str(e)}")
        logger.warning("Server will start but search functionality may not work")

    # Initialize Firestore
    logger.info("Initializing Firestore service")
    try:
        credentials_path = os.path.join(
            os.path.dirname(__file__), "reqagent-c12e92ab61f5.json"
        )
        firestore_service = FirestoreService(
            credentials_path=credentials_path,
            database_name="reqdb"
        )
        logger.info("Successfully initialized Firestore service")
    except Exception as e:
        logger.error(f"Failed to initialize Firestore: {str(e)}")
        logger.warning("Server will start but persistence may not work")


@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint."""
    return {
        "message": "Requirement Gathering API",
        "status": "running"
    }


@app.get("/health")
async def health() -> Dict[str, str]:
    """Health check endpoint."""
    temporal_status = "connected" if temporal_client else "disconnected"
    firestore_status = "connected" if firestore_service else "disconnected"
    return {
        "status": "healthy",
        "temporal": temporal_status,
        "firestore": firestore_status
    }


@app.post("/api/search", response_model=SearchResponse)
async def search_companies(request: SearchRequest) -> SearchResponse:
    """
    Search for companies using Temporal workflow.

    Handles two modes:
    1. Company name search - returns numbered list of matching companies
    2. Number selection - returns detailed JSON info for selected company

    Args:
        request: Search request containing query and optional session_id

    Returns:
        Search response with results
    """
    logger.info(f"Received search request: query={request.query}, session_id={request.session_id}")

    if not temporal_client:
        raise HTTPException(
            status_code=503,
            detail="Temporal client not connected. Please ensure Temporal server is running."
        )

    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    # Generate or use existing session ID
    session_id = request.session_id or str(uuid.uuid4())
    message_id = str(uuid.uuid4())

    # Initialize session if new
    session = firestore_service.get_session(session_id)
    if not session:
        # Create new session with first query as title
        title = request.query[:30] + ("..." if len(request.query) > 30 else "")
        session = firestore_service.create_session(
            session_id=session_id,
            title=title,
            preview=request.query
        )
        logger.info(f"Created new session: {session_id}")

    # Add user message to Firestore
    user_message_timestamp = datetime.datetime.now()
    firestore_service.add_message(
        session_id=session_id,
        message_id=message_id,
        role="user",
        content=request.query,
        timestamp=user_message_timestamp
    )

    try:
        # Check if query is a number (selection mode)
        query_stripped = request.query.strip()
        is_number_selection = query_stripped.isdigit()

        if is_number_selection:
            # Mode 2: User selected a number from the list
            selection_number = int(query_stripped)

            # Get company list from Firestore
            company_list = firestore_service.get_company_list(session_id)

            # Validate selection
            if not company_list:
                raise HTTPException(
                    status_code=400,
                    detail="No company list found. Please search for companies first."
                )
            if selection_number < 1 or selection_number > len(company_list):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid selection. Please choose a number between 1 and {len(company_list)}."
                )

            # Get selected company (1-indexed)
            selected_company = company_list[selection_number - 1]
            company_name = selected_company.get("name")
            company_website = selected_company.get("website")

            logger.info(f"User selected company #{selection_number}: {company_name}")

            # Execute detailed company info workflow
            workflow_id = f"company-detail-{message_id}"
            logger.info(f"Starting detail workflow {workflow_id} for: {company_name}")

            result = await temporal_client.execute_workflow(
                CompanyDetailWorkflow.run,
                args=[company_name, company_website],
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
            )

            logger.info(f"Detail workflow completed: {workflow_id}")

            # Format the detailed info response
            detailed_data = result.get("detailed_info", {}).get("data", {})

            # Generate presumptive configuration using AI
            logger.info("Generating presumptive configuration from company data")
            try:
                config_result = await infer_presumptive_config(detailed_data)
                presumptive_config = config_result.get("data", {})
                logger.info("Presumptive config generated successfully")
            except Exception as e:
                logger.error(f"Error generating config: {str(e)}")
                # Use defaults if AI fails
                presumptive_config = {
                    "industry_sector": "Technology & Software",
                    "sub_sector": "Enterprise Software",
                    "cloud_provider": "AWS",
                    "target_continent": "North America",
                    "region_strategy": "Single Region"
                }

            response_content = {
                "mode": "detailed_info",
                "company_number": selection_number,
                "data": detailed_data,
                "presumptive_config": presumptive_config,
                "show_form": True  # Trigger form display in frontend
            }

        else:
            # Mode 1: User entered a company name - search and list companies
            workflow_id = f"company-search-{message_id}"
            logger.info(f"Starting search workflow {workflow_id} for query: {request.query}")

            result = await temporal_client.execute_workflow(
                CompanySearchWorkflow.run,
                request.query,
                id=workflow_id,
                task_queue=settings.temporal_task_queue,
            )

            logger.info(f"Search workflow completed: {workflow_id}")

            # Extract and number the companies
            search_results = result.get("search_results", {})
            companies = search_results.get("results", [])

            if isinstance(companies, list) and len(companies) > 0:
                # Store the company list in Firestore
                firestore_service.set_company_list(session_id, companies)

                # Create numbered list response
                numbered_companies = []
                for idx, company in enumerate(companies, start=1):
                    numbered_company = {
                        "number": idx,
                        **company
                    }
                    numbered_companies.append(numbered_company)

                response_content = {
                    "mode": "company_list",
                    "count": len(numbered_companies),
                    "companies": numbered_companies,
                    "message": f"Found {len(numbered_companies)} companies. Please enter a number to get detailed information."
                }
            else:
                response_content = {
                    "mode": "company_list",
                    "count": 0,
                    "companies": [],
                    "message": "No companies found matching your search.",
                    "raw_result": result
                }

        # Add assistant response to Firestore
        assistant_message_id = str(uuid.uuid4())
        assistant_message_timestamp = datetime.datetime.now()
        firestore_service.add_message(
            session_id=session_id,
            message_id=assistant_message_id,
            role="assistant",
            content=response_content,
            timestamp=assistant_message_timestamp
        )

        return SearchResponse(
            session_id=session_id,
            message_id=message_id,
            query=request.query,
            results=response_content
        )

    except HTTPException:
        # Re-raise HTTP exceptions
        raise
    except Exception as e:
        logger.error(f"Error executing workflow: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error searching companies: {str(e)}"
        )


@app.get("/api/sessions")
async def list_sessions() -> Dict[str, Any]:
    """
    List all active sessions (last 20, ordered by most recent).

    Returns:
        Dictionary with list of sessions
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        sessions = firestore_service.list_sessions(limit=20)

        # Convert datetime objects to ISO format strings for JSON serialization
        # Also filter out complex nested objects that can't be rendered by React
        for session in sessions:
            if "created_at" in session and session["created_at"]:
                try:
                    session["created_at"] = session["created_at"].isoformat()
                except Exception:
                    session["created_at"] = None
            if "updated_at" in session and session["updated_at"]:
                try:
                    session["updated_at"] = session["updated_at"].isoformat()
                except Exception:
                    session["updated_at"] = None

            # Remove complex nested objects from session list
            # These will be available in the individual session endpoint if needed
            session.pop("questionnaire_results", None)

            # Handle corrupted data where 'title' is an object instead of string
            if "title" in session and isinstance(session["title"], dict):
                # Extract the actual title if it exists, otherwise use session ID
                session["title"] = session.get("id", "Untitled Session")

        return {"sessions": sessions}

    except Exception as e:
        logger.error(f"Error listing sessions: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error listing sessions: {str(e)}"
        )


@app.get("/api/sessions/{session_id}")
async def get_session_with_messages(session_id: str) -> Dict[str, Any]:
    """
    Get session by ID with all messages.

    Args:
        session_id: Session identifier

    Returns:
        Session data with messages
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        data = firestore_service.get_session_with_messages(session_id)

        if not data:
            raise HTTPException(status_code=404, detail="Session not found")

        # Convert datetime objects to ISO format strings
        session = data["session"]
        if "created_at" in session and session["created_at"]:
            session["created_at"] = session["created_at"].isoformat()
        if "updated_at" in session and session["updated_at"]:
            session["updated_at"] = session["updated_at"].isoformat()

        for message in data["messages"]:
            if "timestamp" in message and message["timestamp"]:
                message["timestamp"] = message["timestamp"].isoformat()

        return data

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting session: {str(e)}"
        )


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> Dict[str, str]:
    """
    Delete a chat session and all its messages.

    Args:
        session_id: Session identifier

    Returns:
        Confirmation message
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        # Check if session exists
        session = firestore_service.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Delete session and all messages
        firestore_service.delete_session(session_id)

        return {"message": f"Session {session_id} deleted successfully"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting session: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error deleting session: {str(e)}"
        )


@app.post("/api/generate-config", response_model=ConfigResponse)
async def generate_presumptive_config(request: ConfigRequest) -> ConfigResponse:
    """
    Generate presumptive configuration form values from company data using AI.

    This endpoint uses Temporal activity to call Gemini AI for intelligent
    inference of configuration values based on company information.

    Args:
        request: Contains company_data dictionary

    Returns:
        ConfigResponse with inferred configuration values
    """
    logger.info("Received request to generate presumptive config")

    try:
        # Execute the infer activity directly (not through workflow)
        # We can call activities directly for simple operations
        result = await infer_presumptive_config(request.company_data)

        if result.get("success"):
            logger.info("Successfully generated presumptive config")
            return ConfigResponse(
                success=True,
                data=result.get("data", {})
            )
        else:
            logger.warning(f"Config generation had issues: {result.get('error')}")
            # Still return the default values provided in the result
            return ConfigResponse(
                success=False,
                data=result.get("data", {})
            )

    except Exception as e:
        logger.error(f"Error generating config: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error generating config: {str(e)}"
        )


@app.post("/api/save-config", response_model=ConfigResponse)
async def save_configuration(request: ConfigSaveRequest) -> ConfigResponse:
    """
    Save user's configuration selections to Firestore.

    Args:
        request: Contains session_id and configuration data

    Returns:
        ConfigResponse confirming save operation
    """
    logger.info(
        f"Received request to save config for session: {request.session_id}"
    )

    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        # Validate session exists
        session = firestore_service.get_session(request.session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")

        # Save configuration
        saved_config = firestore_service.save_configuration(
            request.session_id,
            request.configuration
        )

        logger.info(f"Successfully saved config for session: {request.session_id}")

        return ConfigResponse(
            success=True,
            data=saved_config,
            session_id=request.session_id
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving config: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        raise HTTPException(
            status_code=500,
            detail=f"Error saving config: {str(e)}"
        )


@app.get("/api/sessions/{session_id}/config")
async def get_session_config(session_id: str) -> Dict[str, Any]:
    """
    Get saved configuration for a session.

    Args:
        session_id: Session identifier

    Returns:
        Configuration data or empty dict if not found
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        config = firestore_service.get_configuration(session_id)

        if config:
            return {"configuration": config}
        else:
            return {"configuration": None}

    except Exception as e:
        logger.error(f"Error getting config: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting config: {str(e)}"
        )


# ==================== QUESTIONNAIRE ENDPOINTS ====================

@app.get("/api/sessions/{session_id}/questionnaire")
async def get_questionnaire(session_id: str) -> Dict[str, Any]:
    """
    Get saved questionnaire data for a session.

    Args:
        session_id: Session identifier

    Returns:
        Questionnaire data including answers, predictions, and assumptions
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        questionnaire = firestore_service.get_questionnaire(session_id)

        if questionnaire:
            return questionnaire
        else:
            return {
                "answers": {},
                "ai_predictions": {},
                "ai_assumptions": {}
            }

    except Exception as e:
        logger.error(f"Error getting questionnaire: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting questionnaire: {str(e)}"
        )


# LEGACY: Batch prediction endpoint (pre-RAG)
# Kept for fallback/comparison purposes
@app.post("/api/questionnaire/predict")
async def predict_questionnaire_answers(request: QuestionnairePredictRequest) -> Dict[str, Any]:
    """
    Predict answers for questionnaire questions using AI (LEGACY - Batch mode).

    This is the original batch prediction endpoint without RAG enhancement.
    Use /api/questionnaire/predict-with-rag for RAG-enhanced predictions.

    Args:
        request: Prediction request containing question IDs and context

    Returns:
        AI predictions, assumptions, and confidence levels
    """
    try:
        logger.info(f"[LEGACY] Predicting answers for {len(request.question_ids)} questions")

        # Load questions data
        questions_file_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "qna",
            "Questions.json"
        )

        with open(questions_file_path, 'r') as f:
            questions_data = json.load(f)

        # Call the AI activity directly
        result = await infer_questionnaire_answers(
            question_ids=request.question_ids,
            questions_data=questions_data,
            company_data=request.company_data,
            configuration=request.configuration,
            current_answers=request.current_answers
        )

        return result

    except Exception as e:
        logger.error(f"Error predicting questionnaire answers: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error predicting answers: {str(e)}"
        )


@app.post("/api/questionnaire/predict-single")
async def predict_single_question(request: SingleQuestionPredictRequest) -> Dict[str, Any]:
    """
    Predict answer for a single question with RAG enhancement.

    This endpoint processes one question at a time with:
    - Smart RAG filtering (only uses RAG for technical/compliance questions)
    - Context accumulation (considers previous predictions)
    - Document retrieval from RAG API
    - LLM prediction with full context

    Args:
        request: Single question prediction request

    Returns:
        Prediction result with RAG metadata
    """
    try:
        logger.info(f"[RAG] Predicting single question: {request.question_id}")

        # Load questions data
        questions_file_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "qna",
            "Questions.json"
        )

        with open(questions_file_path, 'r') as f:
            questions_data = json.load(f)

        # Find the question
        all_questions = questions_data.get("questions", [])
        question = next(
            (q for q in all_questions if q.get("id") == request.question_id),
            None
        )

        if not question:
            raise HTTPException(
                status_code=404,
                detail=f"Question {request.question_id} not found"
            )

        # Get prediction context
        prediction_context = get_or_create_context(request.session_id)
        context_summary = prediction_context.get_context_summary(
            include_reasoning=True,
            include_sources=False,
            max_predictions=10  # Last 10 predictions for context
        )

        # Call RAG-enhanced prediction activity
        result = await predict_single_question_with_rag(
            question_id=request.question_id,
            question_data=question,
            company_data=request.company_data,
            configuration=request.configuration,
            session_id=request.session_id,
            context_summary=context_summary
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error predicting single question: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error predicting question: {str(e)}"
        )


@app.get("/api/questionnaire/context/{session_id}")
async def get_prediction_context(session_id: str) -> Dict[str, Any]:
    """
    Get prediction context and statistics for a session.

    Args:
        session_id: Session identifier

    Returns:
        Context summary and statistics
    """
    try:
        prediction_context = get_or_create_context(session_id)

        return {
            "session_id": session_id,
            "context_summary": prediction_context.get_context_summary(),
            "statistics": prediction_context.get_statistics(),
            "rag_sources": prediction_context.get_all_rag_sources()
        }

    except Exception as e:
        logger.error(f"Error getting prediction context: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting context: {str(e)}"
        )


@app.post("/api/questionnaire/save")
async def save_questionnaire(request: QuestionnaireSaveRequest) -> Dict[str, Any]:
    """
    Save questionnaire progress to Firestore.

    Args:
        request: Save request containing answers and predictions

    Returns:
        Success confirmation
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        saved_data = firestore_service.save_questionnaire(
            session_id=request.session_id,
            answers=request.answers,
            ai_predictions=request.ai_predictions,
            ai_assumptions=request.ai_assumptions
        )

        logger.info(f"Saved questionnaire progress for session: {request.session_id}")

        return {
            "success": True,
            "saved_at": saved_data.get("saved_at").isoformat() if saved_data.get("saved_at") else None
        }

    except Exception as e:
        logger.error(f"Error saving questionnaire: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error saving questionnaire: {str(e)}"
        )


@app.post("/api/questionnaire/analyze")
async def start_questionnaire_analysis(request: AnalysisRequest) -> Dict[str, Any]:
    """
    Start Temporal workflow for questionnaire analysis.

    This endpoint starts a section-based batch processing workflow that analyzes
    the entire questionnaire with context accumulation and progress tracking.

    Args:
        request: Analysis request with session_id, company_data, configuration

    Returns:
        Dictionary containing workflow_id, session_id, and status
    """
    if not temporal_client:
        raise HTTPException(
            status_code=503,
            detail="Temporal client not initialized."
        )

    try:
        # Parse sections from Questions.json
        section_analyzer = get_section_analyzer()
        section_ids = section_analyzer.get_all_section_ids()

        # Build sections list with metadata
        sections = []
        for section_id in section_ids:
            section_info = section_analyzer.get_section_info(section_id)
            sections.append({
                "id": section_id,
                "title": section_info.get('title', ''),
                "questions_count": len(section_info.get('questions', []))
            })

        logger.info(f"Starting questionnaire analysis for {request.session_id} with {len(sections)} sections")

        # Generate workflow ID
        workflow_id = f"questionnaire-{request.session_id}-{uuid.uuid4().hex[:8]}"

        # Start Temporal workflow
        handle = await temporal_client.start_workflow(
            QuestionnaireAnalysisWorkflow.run,
            args=[
                request.session_id,
                sections,
                request.company_data,
                request.configuration
            ],
            id=workflow_id,
            task_queue=settings.temporal_task_queue
        )

        logger.info(f"Started questionnaire analysis workflow: {workflow_id}")

        return {
            "workflow_id": workflow_id,
            "session_id": request.session_id,
            "status": "started",
            "sections_count": len(sections)
        }

    except Exception as e:
        logger.error(f"Error starting analysis: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error starting analysis: {str(e)}"
        )


@app.get("/api/questionnaire/progress/{workflow_id}")
async def get_analysis_progress(workflow_id: str) -> Dict[str, Any]:
    """
    Query workflow progress for questionnaire analysis.

    Args:
        workflow_id: Workflow identifier

    Returns:
        Dictionary containing workflow status and progress information
    """
    if not temporal_client:
        raise HTTPException(
            status_code=503,
            detail="Temporal client not initialized."
        )

    try:
        # Get workflow handle
        handle = temporal_client.get_workflow_handle(workflow_id)

        # Query workflow progress (non-blocking)
        progress = await handle.query(QuestionnaireAnalysisWorkflow.get_current_progress)

        # Check if workflow is still running
        status = "running"
        workflow_result = None
        try:
            # Try to get result with minimal timeout
            workflow_result = await asyncio.wait_for(handle.result(), timeout=0.1)
            status = "completed"
        except asyncio.TimeoutError:
            status = "running"
        except Exception as e:
            logger.error(f"Workflow error: {str(e)}")
            status = "failed"

        response_data = {
            "workflow_id": workflow_id,
            "status": status,
            "progress": progress
        }

        # Include results if workflow completed
        if status == "completed" and workflow_result:
            response_data["results"] = {
                "predictions": workflow_result.get("predictions", {}),
                "reasoning": workflow_result.get("reasoning", {}),
                "rag_metadata": workflow_result.get("rag_metadata", {})
            }

        return response_data

    except Exception as e:
        logger.error(f"Error getting progress: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error getting progress: {str(e)}"
        )


@app.post("/api/questionnaire/cancel/{workflow_id}")
async def cancel_analysis(workflow_id: str) -> Dict[str, Any]:
    """
    Cancel running questionnaire analysis workflow.

    Args:
        workflow_id: Workflow identifier

    Returns:
        Dictionary confirming cancellation
    """
    if not temporal_client:
        raise HTTPException(
            status_code=503,
            detail="Temporal client not initialized."
        )

    try:
        # Get workflow handle
        handle = temporal_client.get_workflow_handle(workflow_id)

        # Send cancellation signal
        await handle.signal(QuestionnaireAnalysisWorkflow.cancel_analysis)

        logger.info(f"Cancelled workflow: {workflow_id}")

        return {
            "workflow_id": workflow_id,
            "status": "cancelled"
        }

    except Exception as e:
        logger.error(f"Error cancelling workflow: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error cancelling workflow: {str(e)}"
        )


@app.post("/api/questionnaire/submit")
async def submit_questionnaire(request: QuestionnaireSubmitRequest) -> Dict[str, Any]:
    """
    Submit completed questionnaire and generate summary using gemini-deep-search.

    Args:
        request: Submit request containing all answers and context

    Returns:
        Generated summary
    """
    if not firestore_service:
        raise HTTPException(
            status_code=503,
            detail="Firestore service not initialized."
        )

    try:
        logger.info(f"Submitting questionnaire for session: {request.session_id}")

        # Import genai here to avoid circular imports
        import google.generativeai as genai
        from datetime import datetime

        # Configure Gemini with deep search model
        genai.configure(api_key=settings.google_api_key)

        # Use Gemini Deep Search Experimental model for comprehensive summary
        model = genai.GenerativeModel(model_name="gemini-2.0-flash-thinking-exp-1219")

        # Get cloud provider and determine which questions file to load
        cloud_provider = request.configuration.get('cloud_provider', 'AWS')

        # Load appropriate questions data to provide context
        if cloud_provider == 'Azure':
            questions_file_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "qna",
                "questionsazure.json"
            )
        else:
            questions_file_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "qna",
                "Questions.json"
            )

        with open(questions_file_path, 'r') as f:
            questions_data = json.load(f)

        # Get current date in a professional format
        current_date = datetime.now().strftime("%B %d, %Y")

        # Build a comprehensive prompt for summary generation
        prompt = f"""
You are a {cloud_provider} Landing Zone architecture expert. Generate a comprehensive, structured summary report based on the completed questionnaire.

**IMPORTANT: Use the following date in the report: {current_date}**

**Company Information:**
- Company Name: {request.company_data.get('Company name', 'Unknown')}
- Sector: {request.company_data.get('Sector', 'N/A')}
- Sub Sector: {request.company_data.get('Sub Sector', 'N/A')}
- Industry (Config): {request.configuration.get('industry_sector', 'N/A')}
- Cloud Provider: {request.configuration.get('cloud_provider', 'N/A')}
- Target Continent: {request.configuration.get('target_continent', 'N/A')}
- Region Strategy: {request.configuration.get('region_strategy', 'N/A')}
- Global Presence: {request.company_data.get('Global presence', 'N/A')}
- Operating Countries: {request.company_data.get('List of countries they operate in', [])}
- Compliance Requirements: {request.company_data.get('Compliance Requirements', [])}

**Questionnaire Answers:**
{json.dumps(request.answers, indent=2)}

**Summary Requirements:**
Generate a structured, professional {cloud_provider} Landing Zone design document with the following sections:

1. **Executive Summary** (2-3 paragraphs)
   - Overview of the company's requirements
   - Key architectural decisions
   - Overall landing zone strategy

2. **Business Structure**
   - Account/Subscription organization strategy ({"Accounts" if cloud_provider == "AWS" else "Subscriptions" if cloud_provider == "Azure" else "Projects"})
   - Environment segregation approach
   - Business unit or regional structure

3. **Compliance & Security**
   - Regulatory requirements
   - Compliance frameworks
   - Data residency needs
   - Security controls

4. **Network Architecture**
   - Connectivity approach ({"VPN, Direct Connect, hybrid" if cloud_provider == "AWS" else "VPN, ExpressRoute, hybrid" if cloud_provider == "Azure" else "VPN, Interconnect, hybrid"})
   - Network isolation strategy
   - Centralized services design
   - Traffic inspection and routing

5. **Logging & Audit**
   - Centralized logging strategy
   - Log retention policies
   - Access controls for audit logs
   - Log consolidation approach

6. **Disaster Recovery**
   - RTO/RPO requirements
   - DR environment design
   - Failover mechanisms
   - Testing strategy

7. **Recommendations**
   - Key implementation priorities
   - Best practices to follow
   - Potential risks and mitigations

**Format:**
- Use clear headings and subheadings
- Bullet points for clarity
- Professional tone
- Technical but accessible language
- Include specific {cloud_provider} service recommendations where applicable
- **The report title must include: {cloud_provider} Landing Zone Architecture Report**
- **The date in the report must be: {current_date}**

Generate the complete report now:
"""

        # Generate the summary
        generation_config = genai.types.GenerationConfig(
            temperature=0.4,  # Lower temperature for consistent, professional output
            max_output_tokens=8192,
        )

        response = await model.generate_content_async(
            prompt,
            generation_config=generation_config
        )

        summary_text = response.text

        # Save the summary to Firestore
        summary_data = {
            "summary_text": summary_text,
            "model_used": "gemini-2.0-flash-thinking-exp-1219",
            "answers_count": len(request.answers)
        }

        firestore_service.save_questionnaire_summary(
            session_id=request.session_id,
            summary=summary_data
        )

        logger.info(f"Generated and saved summary for session: {request.session_id}")

        return {
            "success": True,
            "summary": summary_text,
            "model_used": "gemini-2.0-flash-thinking-exp-1219"
        }

    except Exception as e:
        logger.error(f"Error submitting questionnaire: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error submitting questionnaire: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info"
    )
