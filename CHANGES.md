# CHANGES.md - Section-Based Questionnaire Processing with Temporal Workflows

**Date**: October 30, 2025  
**Branch**: feature2.1  
**Status**: Planning Document for Implementation

---

## 📋 Table of Contents
1. [Overview](#overview)
2. [Current Architecture](#current-architecture)
3. [Problems Identified](#problems-identified)
4. [Proposed Solution](#proposed-solution)
5. [Detailed Architecture](#detailed-architecture)
6. [Implementation Plan](#implementation-plan)
7. [Code Changes Required](#code-changes-required)
8. [Testing Strategy](#testing-strategy)
9. [Performance Expectations](#performance-expectations)

---

## Overview

### Current Flow
```
User enters company name → Lists companies → User selects one → Company info retrieved → Questionnaire starts
→ For EACH question individually:
   ├── Question + Company Info → RAG API (retrieve chunks)
   ├── Chunks + Question + Company Info → LLM (predict answer)
   └── Store prediction + reasoning
```

### Problem Statement
- **Too many API calls**: Each question triggers separate RAG + LLM calls
- **Time consuming**: ~35 seconds per section (5 questions × 7 seconds each)
- **No context accumulation**: Each question is processed independently
- **Inefficient**: RAG retrieves similar chunks for related questions

### Proposed Solution
Process questions in **section-based batches** using **Temporal workflows**:
- One RAG call per section (instead of per question)
- Batch LLM predictions for multiple questions at once
- Growing context that accumulates across sections
- Wave-based processing to handle dynamic question rendering
- Temporal workflows for reliability, retries, and progress tracking

---

## Current Architecture

### Backend Structure
```
backend/
├── app.py                          # FastAPI server with endpoints
├── worker.py                       # Temporal worker
├── config/
│   └── settings.py                 # Configuration (Temporal, Firestore, Gemini)
├── workflows/
│   ├── company_search_workflow.py  # Company search orchestration
│   └── company_detail_workflow.py  # Company detail retrieval
├── activities/
│   ├── company_search.py           # Search activities
│   └── rag_enhanced_prediction.py  # Per-question RAG + LLM prediction
├── services/
│   ├── rag_client.py               # RAG API client
│   ├── rag_filter.py               # Decides when to use RAG
│   ├── prediction_context.py       # Maintains prediction context
│   └── firestore_service.py        # Firestore persistence
└── qna/
    ├── Questions.json              # Questionnaire structure
    └── rag_config.json             # RAG behavior config
```

### Current Question Processing Flow
```python
# In backend/activities/rag_enhanced_prediction.py
async def predict_single_question_with_rag(question, company_data, config, context):
    # 1. Check if RAG should be used (RAGFilter)
    if should_use_rag(question):
        # 2. Retrieve chunks from RAG API (3-5 seconds)
        chunks = rag_client.retrieve_chunks(question, company_data, top_k=5)
        
    # 3. Call LLM with question + chunks + company data (4-6 seconds)
    prediction = await gemini_predict(question, chunks, company_data, context)
    
    # 4. Store reasoning in context
    context.add_prediction(question_id, prediction, reasoning)
    
    return prediction
```

### Questions.json Structure
```json
{
  "questions": [
    {
      "id": "SEC_BS",
      "title": "BUSINESS STRUCTURE",
      "type": "section"
    },
    {
      "id": "BS_Q1",
      "question": "How is your organization structured?",
      "type": "single",
      "options": [
        { "label": "Environment-wise", "next": ["BS_Q1_ENV"] },
        { "label": "Business Unit-wise", "next": ["BS_Q1_BUS", "BS_Q1_BUS2", "BS_Q1_BUS3"] },
        { "label": "Region-wise", "next": ["BS_Q1_REG"] }
      ]
    },
    {
      "id": "BS_Q1_ENV",
      "question": "Which environments are required?",
      "type": "multi",
      "options": [...]
    }
  ]
}
```

### Dynamic Question Rendering
Questions have **conditional logic** via `next` field:
```json
{
  "id": "CL_Q1",
  "question": "Does your organization operate in a regulated environment?",
  "options": [
    { "label": "Yes", "next": ["CL_Q1_A", "CL_Q1_B", "CL_Q1_C"] },
    { "label": "No" }
  ]
}
```

**Problem**: Can't predict all section questions upfront because some depend on previous answers.

---

## Problems Identified

### 1. Performance Issues
- **Current**: 5 questions × 7 seconds = 35 seconds per section
- **Bottleneck**: Sequential RAG + LLM calls for each question
- **Example**: Business Structure section (5 questions) takes ~35 seconds

### 2. Redundant RAG Calls
- Multiple questions in same section often need similar information
- Example: "How is organization structured?" and "Which environments required?" both need AWS multi-account architecture guidance
- **Current**: Retrieves chunks separately for each question
- **Waste**: Similar chunks retrieved multiple times

### 3. No Context Accumulation Across Sections
- Each section is processed independently
- LLM doesn't know what was decided in previous sections
- **Problem**: Section 3 decisions could benefit from Section 1 context
- **Example**: Network design should consider compliance requirements from earlier section

### 4. Limited Context Within Section
- Context only grows per question, not per section
- Reasoning for Q1 isn't available when predicting Q5 in same section

### 5. API Timeout Risk
- Long-running predictions can timeout
- No progress visibility during processing
- User can't cancel once started

### 6. Error Handling
- If one question's RAG call fails, entire flow stops
- No retry mechanism
- No graceful degradation

---

## Proposed Solution

### Core Concept: Section-Based Batch Processing with Temporal

```
For EACH SECTION (e.g., "Business Structure"):
├── Parse section structure
│   ├── Identify all questions in section
│   ├── Identify root questions (no dependencies)
│   └── Detect section complexity
│
├── [Wave 1] Root Questions
│   ├── Build comprehensive RAG query (all root questions + company info + previous context)
│   ├── ONE RAG call → retrieve 15-20 chunks (cached for entire section)
│   ├── ONE LLM call → predict all root questions in batch
│   └── Resolve next questions based on predictions
│
├── [Wave 2] Revealed Questions (if any)
│   ├── Use SAME cached RAG chunks from Wave 1
│   ├── ONE LLM call → predict revealed questions
│   └── Resolve next questions again
│
├── [Wave N] Continue until no new questions
│
└── Update Growing Context
    ├── Store section predictions + reasoning
    ├── Generate section summary (detailed)
    ├── Compress old sections if context too large
    └── Pass to next section
```

### Key Improvements

#### 1. Section-Based RAG Retrieval
- **ONE RAG call per section** instead of per question
- Comprehensive query includes all section questions
- Higher `top_k` (15-20) to cover multiple questions
- Chunks cached and reused for all waves in section

#### 2. Batch LLM Predictions
- Multiple questions predicted in **ONE LLM call**
- Reduces API overhead and latency
- LLM has full section context for better predictions

#### 3. Growing Context System
- Context accumulates across sections
- Recent sections stored in full detail
- Older sections compressed to summaries
- Max context size: ~2000 tokens (2 sections full + summarized history)

#### 4. Wave-Based Dynamic Resolution
- Process questions in waves to handle conditional logic
- Wave 1: Predict root questions
- Wave 2+: Predict revealed questions using cached RAG chunks
- Continue until no new questions appear

#### 5. Temporal Workflow Orchestration
- **Main Workflow**: `QuestionnaireAnalysisWorkflow` (processes all sections)
- **Child Workflow**: `SectionAnalysisWorkflow` (processes one section with waves)
- **Activities**: RAG retrieval, LLM prediction, context management
- **Benefits**: Retries, progress tracking, cancellation, state persistence

---

## Detailed Architecture

### 1. Temporal Workflow Structure

```
QuestionnaireAnalysisWorkflow (Main)
├── Input: session_id, sections[], company_data, configuration
├── State: accumulated_context, section_results{}
│
├── For each section sequentially:
│   ├── Execute SectionAnalysisWorkflow (child workflow)
│   ├── Pass: section_id, company_data, config, accumulated_context
│   ├── Receive: predictions{}, reasoning{}, rag_metadata{}, updated_context
│   └── Update accumulated_context for next section
│
└── Output: all_predictions, all_reasoning, final_context

SectionAnalysisWorkflow (Child)
├── Input: section_id, company_data, config, previous_context
├── State: wave_number, rag_chunks[] (cached)
│
├── Activity: parse_section_structure
│   └── Returns: section_title, all_questions[], root_questions[]
│
├── Activity: retrieve_section_chunks (ONE TIME)
│   ├── Build comprehensive RAG query
│   ├── Call RAG API with top_k=calculate_optimal_top_k(num_questions)
│   └── Cache chunks for entire section
│
├── While pending_questions exist:
│   ├── wave_number++
│   │
│   ├── Activity: predict_question_batch_with_rag
│   │   ├── Input: questions[], cached_rag_chunks, company_data, context
│   │   ├── Build batch prediction prompt
│   │   ├── Call Gemini LLM
│   │   └── Parse predictions{} + reasoning{}
│   │
│   ├── Activity: resolve_next_questions
│   │   ├── Check predictions for conditional logic
│   │   ├── Find questions revealed by answers
│   │   └── Return newly_revealed_questions[]
│   │
│   └── pending_questions = newly_revealed_questions
│
├── Activity: generate_section_context
│   ├── Build section summary with predictions + reasoning
│   ├── Compress previous_context if > 3000 chars
│   └── Return updated_context
│
└── Output: predictions{}, reasoning{}, rag_metadata{}, updated_context
```

### 2. RAG Query Strategy: Detailed Multi-Question Query

**Format**:
```
Section: {section_title}
Company: {company_name} | Sector: {sector} | Cloud: {cloud_provider}

Questions to answer:
1. {question_1_text}
   Options: {option1}, {option2}, {option3}...
2. {question_2_text}
   Options: {option1}, {option2}...

Context from previous sections:
{compressed_previous_context}

Retrieve {cloud_provider} Landing Zone best practices covering:
- {derived_topics_from_questions}
```

**Example**:
```
Section: Business Structure
Company: Microsoft | Sector: Technology | Cloud: AWS

Questions to answer:
1. How is your organization structured?
   Options: Environment-wise, Business Unit-wise, Region-wise
2. Which environments are required?
   Options: Dev, Test, Prod, Staging, UAT, Sandbox

Retrieve AWS Landing Zone best practices covering:
- AWS Organizations account structure strategies
- Multi-account architecture patterns
- Environment isolation and separation
```

### 3. Context Management Strategy: Smart Hybrid

**Structure**:
```
[RECENT SECTIONS - Full Detail]
Section: {current_or_previous_section_title}
- Q_ID: Predicted Answer
  Reasoning: {full_reasoning_text}

[OLDER SECTIONS - Summarized]
{Section_Title}: {key_decisions_summary}
```

**Rules**:
- **Current section + Previous section**: Store with full reasoning (detailed)
- **Older sections**: Compress to single-line summaries
- **Max total context**: ~2000 tokens (~3000 characters)
- **Compression trigger**: When context exceeds 3000 chars

### 4. Dynamic Question Resolution: Queue-Based Waves

**Algorithm**:
```python
def process_section_with_waves(section_id, root_questions, all_section_questions):
    wave = 1
    pending_questions = root_questions
    all_predictions = {}
    rag_chunks = retrieve_once_for_section()  # CACHED
    
    while pending_questions:
        # Batch predict all pending questions
        predictions = batch_llm_predict(
            questions=pending_questions,
            chunks=rag_chunks,  # REUSE CACHED
            previous_predictions=all_predictions
        )
        all_predictions.update(predictions)
        
        # Resolve next questions
        newly_revealed = []
        for qid, answer in predictions.items():
            question = find_question(qid, all_section_questions)
            next_ids = resolve_next(question, answer)
            newly_revealed.extend(next_ids)
        
        pending_questions = [q for q in all_section_questions if q['id'] in newly_revealed]
        wave += 1
    
    return all_predictions
```

**Example Flow**:
```
Section: Business Structure
Root Questions: [BS_Q1]

Wave 1:
├── Predict: BS_Q1 → "Environment-wise"
└── Revealed: [BS_Q1_ENV]

Wave 2:
├── Predict: BS_Q1_ENV → ["Dev", "Test", "Prod"]
└── Revealed: [] (no more questions)

Section complete: 2 waves, 2 questions predicted
```

### 5. Section Boundary Detection

**Rules**:
1. Section starts with `type: "section"` in Questions.json
2. Section ends when next `type: "section"` appears OR end of array
3. All questions between two section markers belong to first section
4. Nested questions (via `next` field) remain in same section

**Parser Logic**:
```python
def parse_sections_from_json(questions_json):
    sections = {}
    current_section = None
    
    for item in questions_json['questions']:
        if item.get('type') == 'section':
            current_section = {
                'id': item['id'],
                'title': item['title'],
                'questions': []
            }
            sections[item['id']] = current_section
        elif current_section:
            current_section['questions'].append(item)
    
    return sections
```

### 6. Dynamic Top_K Calculation

**Formula**:
```python
def calculate_optimal_top_k(num_questions, section_complexity="medium"):
    """
    Base: 3 chunks per question
    Complexity multipliers:
    - Low: 0.8x (simple yes/no questions)
    - Medium: 1.0x (standard multi-choice)
    - High: 1.5x (complex conditional trees)
    
    Bounds: min=5, max=25 (RAG API limits)
    """
    base_k = 3
    multipliers = {"low": 0.8, "medium": 1.0, "high": 1.5}
    optimal = int(base_k * num_questions * multipliers[section_complexity])
    return max(5, min(25, optimal))

# Examples:
# Business Structure: 5 questions, high → 5*3*1.5 = 22 chunks
# Compliance: 8 questions, high → 8*3*1.5 = 36 → capped at 25
# Logging: 5 questions, medium → 5*3*1.0 = 15 chunks
```

### 7. Error Handling Strategy: Graceful Fallback

**Hierarchy**:
```
Try: Section-level batch processing (optimal)
  ├── RAG retrieval fails
  │   └── Fallback: LLM-only prediction (no RAG context)
  │
  ├── LLM batch prediction fails
  │   └── Fallback: Per-question LLM (slower but works)
  │
  └── Complete failure
      └── Return empty predictions, user answers manually
```

---

## Implementation Plan

### Phase 1: Backend - Core Services (2-3 hours)

#### Step 1.1: Section Analyzer Service
**File**: `backend/services/section_analyzer.py` (NEW)

**Functions**:
- `load_questions_json(file_path)` - Load and parse Questions.json
- `parse_sections(questions)` - Extract sections from questions array
- `get_section_questions(section_id)` - Get all questions in a section
- `find_root_questions(section_questions)` - Find questions not referenced by any 'next' field
- `detect_section_complexity(questions)` - Return 'low', 'medium', or 'high'
- `calculate_optimal_top_k(num_questions, complexity)` - Calculate optimal RAG chunks

#### Step 1.2: Enhanced RAG Client
**File**: `backend/services/rag_client.py` (MODIFY existing)

**New Methods**:
- `retrieve_chunks_for_section()` - Retrieve chunks for entire section with comprehensive query
- `_build_section_query()` - Build multi-question RAG query

#### Step 1.3: Enhanced Context Manager
**File**: `backend/services/prediction_context.py` (MODIFY existing)

**New Methods**:
- `start_new_section()` - Initialize new section context
- `add_section_predictions()` - Add predictions to current section
- `finalize_section()` - Finalize current section and return updated context
- `_build_context_string()` - Build context with smart compression
- `_summarize_section()` - Create one-line summary of section decisions
- `_compress_context()` - Compress context by keeping only recent section

#### Step 1.4: Dynamic Question Resolver
**File**: `backend/services/dynamic_question_resolver.py` (NEW)

**Class**: `DynamicQuestionResolver`
- `resolve_next_questions()` - Determine which questions should be revealed next
- `get_questions_by_ids()` - Convert question IDs to full question objects
- `process_wave()` - Process current wave predictions and return next wave questions

---

### Phase 2: Backend - Temporal Workflows (3-4 hours)

#### Step 2.1: Main Questionnaire Workflow
**File**: `backend/workflows/questionnaire_workflow.py` (NEW)

**Workflow**: `QuestionnaireAnalysisWorkflow`
- Main `run()` method processes all sections sequentially
- Calls `SectionAnalysisWorkflow` as child workflow for each section
- Accumulates context across sections
- Saves final results to Firestore

**Signals & Queries**:
- `@workflow.signal cancel_analysis()` - Handle user cancellation
- `@workflow.query get_current_progress()` - Return current progress for polling
- `@workflow.query get_section_status(section_id)` - Query status of specific section

#### Step 2.2: Section Analysis Child Workflow
**File**: `backend/workflows/section_workflow.py` (NEW)

**Workflow**: `SectionAnalysisWorkflow`
- Processes single section with wave-based resolution
- Calls activities: parse_section, retrieve_chunks, predict_batch, resolve_next, generate_context
- Caches RAG chunks for entire section
- Returns predictions + updated context

---

### Phase 3: Backend - Temporal Activities (3-4 hours)

#### Step 3.1: Section Parsing Activity
**File**: `backend/activities/section_analysis.py` (NEW)

```python
@activity.defn
async def parse_section_structure(section_id: str) -> Dict[str, Any]:
    """Parse section structure from Questions.json"""
    # Returns: section_id, title, all_questions, root_questions, complexity, optimal_top_k
```

#### Step 3.2: RAG Retrieval Activity
```python
@activity.defn
async def retrieve_section_chunks(
    section_title: str,
    questions: List[Dict],
    company_data: Dict,
    configuration: Dict,
    previous_context: str,
    top_k: int = 15
) -> Dict[str, Any]:
    """Retrieve RAG chunks for entire section (ONE CALL)"""
    # Returns: chunks, sources, retrieval_time, query_used
```

#### Step 3.3: Batch Prediction Activity
```python
@activity.defn
async def predict_question_batch_with_rag(
    questions: List[Dict],
    rag_chunks: List[Dict],  # CACHED!
    company_data: Dict,
    configuration: Dict,
    previous_context: str,
    previous_predictions: Dict
) -> Dict[str, Any]:
    """Predict answers for multiple questions using cached RAG chunks"""
    # NO RAG CALL - chunks are pre-retrieved
    # Returns: predictions, reasoning
```

#### Step 3.4: Question Resolution Activity
```python
@activity.defn
async def resolve_next_questions(
    current_questions: List[Dict],
    predictions: Dict[str, Any],
    all_section_questions: List[Dict]
) -> List[str]:
    """Determine which questions should be revealed next"""
    # Pure logic - no API calls
    # Returns: List of next question IDs
```

#### Step 3.5: Context Generation Activity
```python
@activity.defn
async def generate_section_context(
    section_id: str,
    section_title: str,
    predictions: Dict,
    reasoning: Dict,
    previous_context: str
) -> str:
    """Generate updated context summary for next section"""
    # Implements smart compression strategy
    # Returns: updated_context string
```

#### Step 3.6: Progress Update Activity
```python
@activity.defn
async def send_progress_update(
    session_id: str,
    message: str,
    current: int,
    total: int
) -> None:
    """Send progress update to Firestore for frontend polling"""
```

#### Step 3.7: Save Results Activity
```python
@activity.defn
async def save_questionnaire_results(
    session_id: str,
    predictions: Dict,
    reasoning: Dict,
    rag_metadata: Dict,
    final_context: str
) -> None:
    """Save complete results to Firestore"""
```

---

### Phase 4: Backend - API Endpoints (1-2 hours)

#### Step 4.1: New Endpoint - Start Workflow
**File**: `backend/app.py` (MODIFY)

```python
@app.post("/api/questionnaire/analyze")
async def start_questionnaire_analysis(request: AnalysisRequest):
    """
    Start Temporal workflow for questionnaire analysis.
    
    Request:
    {
        "session_id": str,
        "company_data": dict,
        "configuration": dict
    }
    
    Response:
    {
        "workflow_id": str,
        "session_id": str,
        "status": "started"
    }
    """
    # Parse sections from Questions.json
    sections = parse_sections()
    
    # Start Temporal workflow
    workflow_id = f"questionnaire-{session_id}-{timestamp}"
    handle = await temporal_client.start_workflow(
        QuestionnaireAnalysisWorkflow.run,
        args=[session_id, sections, company_data, configuration],
        id=workflow_id,
        task_queue=settings.temporal_task_queue
    )
    
    return {
        "workflow_id": workflow_id,
        "session_id": session_id,
        "status": "started"
    }
```

#### Step 4.2: New Endpoint - Get Progress
```python
@app.get("/api/questionnaire/progress/{workflow_id}")
async def get_analysis_progress(workflow_id: str):
    """
    Query workflow progress.
    
    Response:
    {
        "workflow_id": str,
        "status": "running" | "completed" | "failed",
        "progress": {
            "sections_completed": int,
            "total_sections": int,
            "predictions_made": int
        }
    }
    """
    handle = temporal_client.get_workflow_handle(workflow_id)
    
    # Query workflow progress (non-blocking)
    progress = await handle.query(
        QuestionnaireAnalysisWorkflow.get_current_progress
    )
    
    # Check if workflow is still running
    status = "running"
    try:
        result = await handle.result(timeout=0.1)
        status = "completed"
    except asyncio.TimeoutError:
        status = "running"
    except Exception:
        status = "failed"
    
    return {
        "workflow_id": workflow_id,
        "status": status,
        "progress": progress
    }
```

#### Step 4.3: New Endpoint - Cancel Analysis
```python
@app.post("/api/questionnaire/cancel/{workflow_id}")
async def cancel_analysis(workflow_id: str):
    """
    Cancel running workflow.
    
    Response:
    {
        "workflow_id": str,
        "status": "cancelled"
    }
    """
    handle = temporal_client.get_workflow_handle(workflow_id)
    await handle.signal(QuestionnaireAnalysisWorkflow.cancel_analysis)
    
    return {
        "workflow_id": workflow_id,
        "status": "cancelled"
    }
```

#### Step 4.4: Modify Endpoint - Get Results
```python
@app.get("/api/sessions/{session_id}/questionnaire")
async def get_questionnaire_results(session_id: str):
    """
    Get questionnaire results (existing endpoint, no changes needed)
    
    This already retrieves from Firestore, which is where
    save_questionnaire_results activity stores the data.
    """
    # Existing implementation remains unchanged
```

---

### Phase 5: Backend - Worker Updates (30 minutes)

#### Step 5.1: Register New Workflows and Activities
**File**: `backend/worker.py` (MODIFY)

```python
from workflows import (
    CompanySearchWorkflow,
    CompanyDetailWorkflow,
    QuestionnaireAnalysisWorkflow,  # NEW
    SectionAnalysisWorkflow  # NEW
)

from activities import (
    # Existing activities
    search_companies,
    parse_company_input,
    get_detailed_company_info,
    infer_presumptive_config,
    infer_questionnaire_answers,
    predict_single_question_with_rag,
    # NEW activities
    parse_section_structure,
    retrieve_section_chunks,
    predict_question_batch_with_rag,
    resolve_next_questions,
    generate_section_context,
    send_progress_update,
    save_questionnaire_results
)

async def main():
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[
            CompanySearchWorkflow,
            CompanyDetailWorkflow,
            QuestionnaireAnalysisWorkflow,  # NEW
            SectionAnalysisWorkflow  # NEW
        ],
        activities=[
            # All existing + new activities
            search_companies,
            parse_company_input,
            get_detailed_company_info,
            infer_presumptive_config,
            infer_questionnaire_answers,
            predict_single_question_with_rag,
            parse_section_structure,
            retrieve_section_chunks,
            predict_question_batch_with_rag,
            resolve_next_questions,
            generate_section_context,
            send_progress_update,
            save_questionnaire_results
        ]
    )
    
    await worker.run()
```

---

### Phase 6: Frontend - Integration (1-2 hours)

#### Step 6.1: Update Questionnaire Component
**File**: `frontend/src/pages/Questionnaire.jsx` (MODIFY)

**Changes**:

1. **Replace per-question processing with workflow start**:
```javascript
const startQuestionnaireAnalysis = async () => {
  try {
    setAnalyzing(true);
    setError(null);
    
    // Start Temporal workflow
    const response = await axios.post(
      `${API_BASE_URL}/api/questionnaire/analyze`,
      {
        session_id: sessionId,
        company_data: companyData,
        configuration: configData
      }
    );
    
    const workflowId = response.data.workflow_id;
    setCurrentWorkflowId(workflowId);
    
    // Start polling for progress
    pollWorkflowProgress(workflowId);
    
  } catch (err) {
    console.error('Error starting analysis:', err);
    setError('Failed to start analysis');
  }
};
```

2. **Add progress polling**:
```javascript
const pollWorkflowProgress = async (workflowId) => {
  const pollInterval = setInterval(async () => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/api/questionnaire/progress/${workflowId}`
      );
      
      const { status, progress } = response.data;
      
      // Update progress UI
      setProcessingProgress({
        current: progress.sections_completed,
        total: progress.total_sections,
        predictions_made: progress.predictions_made,
        isProcessing: status === 'running'
      });
      
      // If completed, load results
      if (status === 'completed') {
        clearInterval(pollInterval);
        await loadQuestionnaireResults();
        setAnalyzing(false);
      }
      
      // If failed, show error
      if (status === 'failed') {
        clearInterval(pollInterval);
        setError('Analysis failed. Please try again.');
        setAnalyzing(false);
      }
      
    } catch (err) {
      console.error('Error polling progress:', err);
    }
  }, 2000);  // Poll every 2 seconds
  
  // Store interval ID for cleanup
  setProgressPollInterval(pollInterval);
};
```

3. **Add cancel button**:
```javascript
const handleCancelAnalysis = async () => {
  try {
    await axios.post(
      `${API_BASE_URL}/api/questionnaire/cancel/${currentWorkflowId}`
    );
    
    // Clear polling interval
    if (progressPollInterval) {
      clearInterval(progressPollInterval);
    }
    
    setAnalyzing(false);
    setError('Analysis cancelled');
    
  } catch (err) {
    console.error('Error cancelling analysis:', err);
  }
};
```

4. **Update progress indicator UI**:
```javascript
{processingProgress.isProcessing && (
  <div className="analysis-progress">
    <div className="progress-header">
      <h3>Analyzing Questionnaire...</h3>
      <button onClick={handleCancelAnalysis} className="cancel-btn">
        Cancel
      </button>
    </div>
    
    <div className="progress-bar-container">
      <div
        className="progress-bar-fill"
        style={{
          width: `${(processingProgress.current / processingProgress.total) * 100}%`
        }}
      />
    </div>
    
    <div className="progress-details">
      <p>Section {processingProgress.current} of {processingProgress.total}</p>
      <p>{processingProgress.predictions_made} predictions made</p>
    </div>
  </div>
)}
```

5. **Remove per-question processing code**:
```javascript
// DELETE: Old useEffect that called performAIAnalysis for each question
// DELETE: Old performAIAnalysis function
// DELETE: Per-question RAG toggle logic (now section-level)
```

#### Step 6.2: Update UI Components
**File**: `frontend/src/pages/Questionnaire.css` (MODIFY)

**Add styles**:
```css
.analysis-progress {
  background: var(--card-bg);
  border-radius: 12px;
  padding: 24px;
  margin-bottom: 24px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.progress-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.cancel-btn {
  background: var(--danger-color);
  color: white;
  border: none;
  padding: 8px 16px;
  border-radius: 6px;
  cursor: pointer;
}

.progress-bar-container {
  width: 100%;
  height: 8px;
  background: var(--gray-200);
  border-radius: 4px;
  overflow: hidden;
  margin-bottom: 12px;
}

.progress-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary-color), var(--accent-color));
  transition: width 0.3s ease;
}

.progress-details {
  display: flex;
  justify-content: space-between;
  font-size: 14px;
  color: var(--text-secondary);
}
```

---

### Phase 7: Testing & Validation (2-3 hours)

#### Step 7.1: Unit Tests

**Test Section Analyzer**:
```python
# backend/tests/test_section_analyzer.py
def test_parse_sections():
    analyzer = SectionAnalyzer("qna/Questions.json")
    sections = analyzer.parse_sections()
    
    assert 'SEC_BS' in sections
    assert sections['SEC_BS'].title == 'BUSINESS STRUCTURE'
    assert len(sections['SEC_BS'].questions) > 0

def test_find_root_questions():
    # Test with sample section
    questions = [
        {"id": "Q1", "next": ["Q2"]},
        {"id": "Q2", "options": [{"next": ["Q3"]}]},
        {"id": "Q3"}
    ]
    roots = find_root_questions(questions)
    assert len(roots) == 1
    assert roots[0]['id'] == 'Q1'

def test_calculate_optimal_top_k():
    assert calculate_optimal_top_k(3, "low") == 7
    assert calculate_optimal_top_k(5, "medium") == 15
    assert calculate_optimal_top_k(8, "high") == 25  # Capped
```

**Test Dynamic Resolver**:
```python
# backend/tests/test_dynamic_resolver.py
def test_resolve_next_questions():
    questions = load_test_questions()
    resolver = DynamicQuestionResolver(questions)
    
    # Test single-choice with next
    next_ids = resolver.resolve_next_questions("BS_Q1", "Environment-wise")
    assert "BS_Q1_ENV" in next_ids
    
    # Test multi-choice
    next_ids = resolver.resolve_next_questions("CL_Q1", "Yes")
    assert all(x in next_ids for x in ["CL_Q1_A", "CL_Q1_B", "CL_Q1_C"])
```

**Test Context Manager**:
```python
# backend/tests/test_context_manager.py
def test_context_compression():
    context = PredictionContext()
    
    # Add multiple sections
    for i in range(5):
        context.start_new_section(f"SEC_{i}", f"Section {i}")
        context.add_section_predictions({f"Q{i}": f"Answer{i}"}, {})
        context.finalize_section()
    
    context_str = context._build_context_string()
    
    # Should have compressed older sections
    assert len(context_str) < 5000
    assert "[RECENT SECTIONS" in context_str
    assert "[OLDER SECTIONS" in context_str
```

#### Step 7.2: Integration Tests

**Test Workflow Execution**:
```python
# backend/tests/test_workflows.py
@pytest.mark.asyncio
async def test_questionnaire_workflow():
    # Start workflow
    handle = await temporal_client.start_workflow(
        QuestionnaireAnalysisWorkflow.run,
        args=[
            "test-session",
            ["SEC_BS", "SEC_CL"],
            sample_company_data,
            sample_configuration
        ],
        id="test-workflow-1",
        task_queue="test-queue"
    )
    
    # Wait for completion
    result = await handle.result()
    
    # Validate result
    assert result['session_id'] == "test-session"
    assert result['total_predictions'] > 0
    assert result['sections_processed'] == 2
```

**Test API Endpoints**:
```python
# backend/tests/test_api.py
def test_start_analysis_endpoint(client):
    response = client.post("/api/questionnaire/analyze", json={
        "session_id": "test-session",
        "company_data": sample_company_data,
        "configuration": sample_configuration
    })
    
    assert response.status_code == 200
    assert "workflow_id" in response.json()

def test_progress_endpoint(client):
    # Assuming workflow is running
    response = client.get("/api/questionnaire/progress/test-workflow-1")
    
    assert response.status_code == 200
    assert "status" in response.json()
    assert "progress" in response.json()
```

#### Step 7.3: End-to-End Testing

**Manual Test Plan**:

1. **Start questionnaire analysis**:
   - Navigate to questionnaire page
   - Click "Start Analysis" (or auto-start)
   - Verify workflow starts and progress bar appears

2. **Monitor progress**:
   - Watch progress bar update every 2 seconds
   - Verify section-by-section progress
   - Check Temporal UI to see workflow execution

3. **Test cancellation**:
   - Start analysis
   - Click "Cancel" button mid-way
   - Verify workflow stops and UI updates

4. **Test completion**:
   - Let analysis complete
   - Verify predictions are loaded
   - Check that assumptions/reasoning are displayed
   - Verify RAG sources are shown

5. **Test error handling**:
   - Stop Temporal worker mid-analysis
   - Verify UI shows error gracefully
   - Restart worker and retry

6. **Test with different sections**:
   - Business Structure (conditional questions)
   - Compliance (multi-level conditionals)
   - Logging (simpler questions)
   - Network (complex dependencies)

---

## Code Changes Required

### New Files to Create

1. **`backend/services/section_analyzer.py`**
   - Section parsing logic
   - Root question detection
   - Complexity analysis
   - Top_k calculation

2. **`backend/services/dynamic_question_resolver.py`**
   - Dynamic question resolution
   - Wave processing logic
   - Next question determination

3. **`backend/workflows/questionnaire_workflow.py`**
   - Main QuestionnaireAnalysisWorkflow
   - Workflow signals and queries

4. **`backend/workflows/section_workflow.py`**
   - SectionAnalysisWorkflow (child workflow)
   - Wave-based processing

5. **`backend/activities/section_analysis.py`**
   - All new activities:
     - parse_section_structure
     - retrieve_section_chunks
     - predict_question_batch_with_rag
     - resolve_next_questions
     - generate_section_context
     - send_progress_update
     - save_questionnaire_results

6. **Test files**:
   - `backend/tests/test_section_analyzer.py`
   - `backend/tests/test_dynamic_resolver.py`
   - `backend/tests/test_context_manager.py`
   - `backend/tests/test_workflows.py`
   - `backend/tests/test_api.py`

### Files to Modify

1. **`backend/services/rag_client.py`**
   - Add `retrieve_chunks_for_section()` method
   - Add `_build_section_query()` helper

2. **`backend/services/prediction_context.py`**
   - Add section-aware methods
   - Add compression logic
   - Add context summary generation

3. **`backend/app.py`**
   - Add `/api/questionnaire/analyze` endpoint
   - Add `/api/questionnaire/progress/{workflow_id}` endpoint
   - Add `/api/questionnaire/cancel/{workflow_id}` endpoint

4. **`backend/worker.py`**
   - Register new workflows
   - Register new activities

5. **`frontend/src/pages/Questionnaire.jsx`**
   - Replace per-question processing
   - Add workflow start logic
   - Add progress polling
   - Add cancel functionality
   - Update UI components

6. **`frontend/src/pages/Questionnaire.css`**
   - Add progress bar styles
   - Add cancel button styles

### Files to Keep (No Changes)

- `backend/services/firestore_service.py` - Already has needed methods
- `backend/services/rag_filter.py` - Can be used for section-level filtering if needed
- `backend/workflows/company_search_workflow.py` - Unchanged
- `backend/workflows/company_detail_workflow.py` - Unchanged
- `qna/Questions.json` - Structure remains the same
- All frontend files except Questionnaire.jsx and CSS

### Files to Deprecate (Keep for Fallback)

- `backend/activities/rag_enhanced_prediction.py`
  - Keep `predict_single_question_with_rag` as fallback
  - May be used if section-level processing fails

---

## Testing Strategy

### 1. Unit Testing

**Focus Areas**:
- Section parsing logic
- Root question detection
- Dynamic question resolution
- Context compression
- Top_k calculation

**Tools**: pytest, pytest-asyncio

### 2. Integration Testing

**Focus Areas**:
- Workflow execution end-to-end
- Activity execution with retries
- API endpoint responses
- Firestore persistence

**Tools**: pytest, Temporal testing framework

### 3. Performance Testing

**Metrics to Track**:
- Section processing time (target: 10-15s per section)
- RAG retrieval time (target: <5s)
- LLM batch prediction time (target: <6s)
- Total questionnaire time (target: <90s for 5 sections)

**Comparison**:
- Old: 5 sections × 35s = 175 seconds
- New: 5 sections × 15s = 75 seconds
- **Target: 57% improvement**

### 4. Error Recovery Testing

**Scenarios**:
- RAG API timeout
- LLM API failure
- Temporal worker crash mid-workflow
- Network interruption
- User cancellation

**Expected Behavior**:
- Graceful degradation
- Automatic retries
- Workflow resume after worker restart
- Clean cancellation without data loss

### 5. Load Testing

**Scenarios**:
- 10 concurrent users starting questionnaires
- 50 concurrent workflow executions
- Temporal queue saturation

**Tools**: Locust, JMeter

---

## Performance Expectations

### Current Performance (Per-Question Processing)

```
Section with 5 questions:
├── Q1: RAG (3s) + LLM (4s) = 7s
├── Q2: RAG (3s) + LLM (4s) = 7s
├── Q3: RAG (3s) + LLM (4s) = 7s
├── Q4: RAG (3s) + LLM (4s) = 7s
└── Q5: RAG (3s) + LLM (4s) = 7s
Total: 35 seconds per section

Full questionnaire (5 sections):
5 × 35s = 175 seconds (~3 minutes)
```

### Expected Performance (Section-Batch Processing)

```
Section with 5 questions:
├── Parse section: 0.5s
├── RAG retrieval (ONE call): 5s
├── Wave 1 (3 questions): LLM batch (6s)
├── Wave 2 (2 questions): LLM batch (4s)
└── Context generation: 0.5s
Total: ~16 seconds per section

Full questionnaire (5 sections):
5 × 16s = 80 seconds (~1.3 minutes)

Improvement: 175s → 80s = 54% faster! ⚡
```

### Best Case Performance

```
Section with simple questions (no waves):
├── Parse: 0.5s
├── RAG: 4s
├── LLM batch: 5s
└── Context: 0.5s
Total: ~10 seconds

Full questionnaire: 5 × 10s = 50 seconds (71% faster!)
```

### Worst Case Performance

```
Section with complex waves (3+ waves):
├── Parse: 0.5s
├── RAG: 6s
├── Wave 1: 6s
├── Wave 2: 5s
├── Wave 3: 4s
└── Context: 0.5s
Total: ~22 seconds

Full questionnaire: 5 × 22s = 110 seconds (37% faster)
```

### Scaling Benefits

**Temporal Advantages**:
- Parallel section processing possible (if sections are independent)
- Workflow can run for hours without timeout
- Automatic retry on transient failures
- State persistence across worker restarts
- Real-time progress visibility

**RAG Efficiency**:
- 80% reduction in RAG calls (5 questions → 1 call per section)
- Chunk reuse across waves
- Better chunk relevance with comprehensive queries

**LLM Efficiency**:
- 60% reduction in LLM calls (batch predictions)
- Better predictions with full section context
- Lower API costs

---

## Risk Mitigation

### Risks Identified

1. **Complex LLM Prompts**
   - Risk: Batch prompts may be too long (token limit)
   - Mitigation: Limit to 10 questions per batch, split if needed

2. **Wave Detection Issues**
   - Risk: Infinite loop in wave processing
   - Mitigation: Max wave limit (5 waves), timeout after 60s

3. **Context Growth**
   - Risk: Context exceeds token limits
   - Mitigation: Aggressive compression, 3000 char limit

4. **Temporal Learning Curve**
   - Risk: Team unfamiliar with Temporal concepts
   - Mitigation: Comprehensive documentation, examples

5. **Migration Complexity**
   - Risk: Breaking existing functionality
   - Mitigation: Keep old code as fallback, gradual rollout

### Rollback Plan

If issues arise in production:

1. **Immediate**: Disable new endpoints, redirect to old per-question processing
2. **Short-term**: Fix issues in new code, deploy hotfix
3. **Long-term**: If unfixable, revert to old architecture

**Rollback Trigger**: >20% error rate or >2x slower than old system

---

## Deployment Plan

### Phase 1: Development (Week 1-2)
- Implement all backend components
- Write unit tests
- Test in local development

### Phase 2: Integration (Week 3)
- Deploy to dev environment
- Run integration tests
- Fix issues

### Phase 3: Staging (Week 4)
- Deploy to staging
- Performance testing
- Load testing
- UAT (User Acceptance Testing)

### Phase 4: Production (Week 5)
- Gradual rollout:
  - Day 1: 10% of users (feature flag)
  - Day 2-3: Monitor metrics, increase to 50%
  - Day 4-5: 100% rollout if metrics are good

### Monitoring Metrics

**Success Criteria**:
- ✅ Section processing time: <20s per section
- ✅ Error rate: <5%
- ✅ User satisfaction: >80% positive feedback
- ✅ Performance improvement: >40% faster than old system

**Alert Thresholds**:
- 🚨 Section processing time: >30s
- 🚨 Error rate: >10%
- 🚨 Workflow failures: >3 per hour

---

## Appendix

### A. Glossary

- **Section**: Group of related questions in questionnaire (e.g., "Business Structure")
- **Wave**: Iteration of question processing within a section
- **Root Question**: Question with no dependencies (visible immediately)
- **Revealed Question**: Question that appears based on previous answer
- **RAG**: Retrieval-Augmented Generation (document retrieval system)
- **Temporal**: Workflow orchestration platform
- **Top_k**: Number of document chunks to retrieve from RAG

### B. References

- Temporal Documentation: https://docs.temporal.io/
- Questions.json: `/qna/Questions.json`
- Current RAG Implementation: `/backend/activities/rag_enhanced_prediction.py`
- Current Context Manager: `/backend/services/prediction_context.py`

### C. Key Decision Log

| Date | Decision | Rationale |
|------|----------|-----------|
| 2025-10-30 | Section-based batch processing | Reduce API calls by 80% |
| 2025-10-30 | Temporal workflows instead of direct calls | Enable retries, progress tracking, cancellation |
| 2025-10-30 | Wave-based dynamic resolution | Handle conditional question logic |
| 2025-10-30 | Smart context compression | Prevent token limit issues |
| 2025-10-30 | Dynamic top_k calculation | Optimize RAG retrieval per section complexity |

---

**End of Document**

*This document will be updated as implementation progresses.*
