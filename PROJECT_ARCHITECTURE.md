# 📋 Complete Project Architecture - ReqAgent

## 🎯 Project Overview

**ReqAgent** is an AI-powered requirements gathering and questionnaire system for cloud landing zone design. It combines:
- Company search using Google Gemini with web grounding
- AI-powered configuration inference
- RAG-enhanced questionnaire prediction
- Document generation using deep-thinking AI models

---

## 🏗️ System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                         │
│  - Company Search Interface                                      │
│  - Configuration Form                                            │
│  - Dynamic Questionnaire                                         │
│  - Session Management                                            │
└─────────────────────────────────────────────────────────────────┘
                                ↓ HTTP/REST
┌─────────────────────────────────────────────────────────────────┐
│                      BACKEND (FastAPI)                           │
│  - API Endpoints (/api/search, /api/questionnaire, etc.)        │
│  - Session Management                                            │
│  - Temporal Workflow Orchestration                               │
└─────────────────────────────────────────────────────────────────┘
                    ↓                           ↓
        ┌───────────────────┐       ┌──────────────────┐
        │  Temporal Worker   │       │  Firestore DB    │
        │  - Workflows       │       │  - Sessions      │
        │  - Activities      │       │  - Messages      │
        └───────────────────┘       │  - Config        │
                    ↓                │  - Questionnaire │
        ┌───────────────────┐       └──────────────────┘
        │  Gemini 2.0 Flash │
        │  (with grounding) │
        └───────────────────┘
                    ↓
        ┌───────────────────┐
        │    RAG API        │
        │  (localhost:5000)  │
        │  - AWS Docs       │
        │  - 30K+ chunks    │
        └───────────────────┘
```

---

## 📁 Project Structure

```
ReqAgent/
├── backend/                          # Python FastAPI Backend
│   ├── config/                       # Configuration
│   │   ├── settings.py              # App settings (Gemini, Temporal, etc.)
│   │   └── __init__.py
│   │
│   ├── workflows/                    # Temporal Workflows
│   │   ├── company_search_workflow.py    # Search companies workflow
│   │   ├── company_detail_workflow.py    # Get detailed info workflow
│   │   └── __init__.py
│   │
│   ├── activities/                   # Temporal Activities
│   │   ├── company_search.py        # Company search, parsing, details
│   │   ├── rag_enhanced_prediction.py    # RAG-powered Q&A prediction
│   │   └── __init__.py
│   │
│   ├── services/                     # Business Logic Services
│   │   ├── firestore_service.py     # Firestore CRUD operations
│   │   ├── rag_client.py            # RAG API client wrapper
│   │   ├── rag_filter.py            # Smart RAG routing logic
│   │   ├── prediction_context.py    # Context accumulation for predictions
│   │   └── __init__.py
│   │
│   ├── app.py                       # FastAPI server (main entry point)
│   ├── worker.py                    # Temporal worker (processes workflows)
│   ├── requirements.txt             # Python dependencies
│   ├── pyproject.toml              # Black/isort config
│   └── reqagent-c12e92ab61f5.json  # Firestore credentials
│
├── frontend/                         # React + Vite Frontend
│   ├── src/
│   │   ├── App.jsx                  # Main app with routing
│   │   ├── App.css                  # Styling
│   │   ├── main.jsx                 # Entry point
│   │   └── pages/
│   │       └── Questionnaire.jsx    # Dynamic questionnaire page
│   ├── package.json                 # Node dependencies
│   └── vite.config.js              # Vite config
│
├── qna/                             # Questionnaire Data
│   ├── Questions.json              # AWS questionnaire (114 questions)
│   ├── questionsazure.json         # Azure questionnaire
│   └── rag_config.json             # RAG routing configuration
│
├── agent-development-kit-crash-course-main/  # Learning resources
│
├── docker-compose.yml              # Temporal server setup
├── README.md                       # Main documentation
├── PROJECT_SUMMARY.md              # High-level summary
├── FEATURE_GUIDE.md                # Two-stage search guide
├── RAG_INTEGRATION.md              # RAG API integration guide
└── [other docs...]
```

---

## 🔄 Complete User Journey

### Journey 1: Company Search → Configuration

1. **User enters company name** (e.g., "MetLife")
   - Frontend: `App.jsx` → `/api/search`
   - Backend: `app.py` → `CompanySearchWorkflow`
   - Activity: `search_companies()` → Gemini AI
   - Response: **List of 3 companies as cards**

2. **User selects a company** (clicks "Select" button)
   - Frontend sends company number → `/api/search`
   - Backend: `CompanyDetailWorkflow`
   - Activity: `get_detailed_company_info()` → Gemini AI
   - Response: **Detailed JSON with 10+ fields**

3. **AI generates presumptive configuration**
   - Activity: `infer_presumptive_config()`
   - Analyzes: Sector, location, compliance, etc.
   - Returns: Industry, cloud provider, region strategy

4. **User reviews/edits configuration form**
   - Inline form displayed in chat
   - User can modify AI suggestions
   - Saves to Firestore on submit

5. **User clicks "Continue Questionnaire"**
   - Navigates to `/questionnaire/:sessionId`
   - Loads dynamic questionnaire based on cloud provider

### Journey 2: AI-Assisted Questionnaire

1. **Questionnaire loads** (`Questionnaire.jsx`)
   - Fetches Questions.json (AWS) or questionsazure.json (Azure)
   - 114 questions across 6 sections
   - Sections: Business Structure, Compliance, Network, DR, Logging, Assumptions

2. **User clicks "Get AI Suggestions"**
   - Frontend → `/api/questionnaire/predict-single`
   - Backend: `predict_single_question_with_rag()`

3. **RAG Filter determines if question needs docs**
   - Smart routing based on question type
   - Technical questions → RAG enabled
   - Business questions → Company data only

4. **If RAG enabled:**
   - Query RAG API (localhost:5000)
   - Retrieve 5 relevant AWS document chunks
   - Build enhanced prompt with docs

5. **Gemini generates prediction**
   - Context: Company data + Config + RAG docs + Previous answers
   - Output: Answer + Reasoning + Confidence
   - Frontend displays with green checkmark + justification

6. **Context accumulates** (`prediction_context.py`)
   - Stores each prediction
   - Next predictions consider previous choices
   - Maintains consistency across 114 questions

7. **User completes questionnaire**
   - Manual answers + AI suggestions
   - Saved to Firestore continuously

8. **User clicks "Submit & Generate Report"**
   - Backend: `gemini-2.0-flash-thinking-exp-1219` (deep search)
   - Generates comprehensive architecture document
   - Sections: Executive Summary, Business Structure, Compliance, Network, DR, Recommendations
   - Report saved to Firestore

---

## 🧠 AI Models Used

| Model | Purpose | Temperature | Use Case |
|-------|---------|-------------|----------|
| **gemini-2.0-flash-exp** | Company search, details, config inference | 0.5-0.7 | Fast, grounded searches |
| **gemini-2.0-flash-exp** | Questionnaire prediction | 0.4 | Consistent predictions |
| **gemini-2.0-flash-thinking-exp-1219** | Final report generation | 0.4 | Deep, comprehensive analysis |

---

## 🗄️ Database Schema (Firestore)

### Collection: `sessions`

```javascript
{
  id: "uuid",
  title: "MetLife Search",
  preview: "metlife",
  created_at: Timestamp,
  updated_at: Timestamp,
  company_list: [
    { number: 1, name: "MetLife, Inc.", ... }
  ],
  configuration: {
    industry_sector: "Financial Services",
    sub_sector: "Insurance",
    cloud_provider: "AWS",
    target_continent: "North America",
    region_strategy: "Primary + DR",
    saved_at: Timestamp
  },
  questionnaire: {
    answers: { "BS_Q1": "Multi-Account", ... },
    ai_predictions: { "BS_Q1": "Multi-Account", ... },
    ai_assumptions: { "BS_Q1": "Reasoning...", ... },
    saved_at: Timestamp
  },
  questionnaire_summary: {
    summary_text: "Full markdown report...",
    model_used: "gemini-2.0-flash-thinking-exp-1219",
    answers_count: 114,
    generated_at: Timestamp
  }
}
```

### Subcollection: `sessions/{id}/messages`

```javascript
{
  id: "uuid",
  role: "user" | "assistant",
  content: "string" | { mode: "company_list", companies: [...] },
  timestamp: Timestamp
}
```

---

## 🔌 API Endpoints

### Backend (Port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| **GET** | `/` | Root endpoint |
| **GET** | `/health` | Health check (Temporal + Firestore status) |
| **POST** | `/api/search` | Search companies or get details |
| **GET** | `/api/sessions` | List all sessions (last 20) |
| **GET** | `/api/sessions/{id}` | Get session with messages |
| **DELETE** | `/api/sessions/{id}` | Delete session |
| **POST** | `/api/generate-config` | Generate presumptive config (AI) |
| **POST** | `/api/save-config` | Save configuration |
| **GET** | `/api/sessions/{id}/config` | Get saved config |
| **GET** | `/api/sessions/{id}/questionnaire` | Get saved questionnaire |
| **POST** | `/api/questionnaire/predict` | Batch prediction (LEGACY) |
| **POST** | `/api/questionnaire/predict-single` | Single question with RAG |
| **GET** | `/api/questionnaire/context/{id}` | Get prediction context |
| **POST** | `/api/questionnaire/save` | Save questionnaire progress |
| **POST** | `/api/questionnaire/submit` | Submit & generate report |

### RAG API (Port 5000) - External Service

| Method | Endpoint | Description |
|--------|----------|-------------|
| **GET** | `/api/health` | RAG API health check |
| **POST** | `/api/retrieve` | Retrieve document chunks |
| **GET** | `/api/stats` | Get collection statistics |

---

## 🔐 Key Technologies

### Backend Stack
- **FastAPI** 0.115.0 - Async REST API framework
- **Temporal.io** 1.6.0 - Workflow orchestration
- **Google Generative AI** 0.8.3 - Gemini models
- **Firebase Admin** - Firestore database client
- **Pydantic** 2.9.2 - Data validation
- **Python** 3.11+

### Frontend Stack
- **React** 18 - UI library
- **Vite** 5 - Build tool
- **React Router** - Routing
- **Framer Motion** - Animations
- **Axios** - HTTP client
- **React Icons** - Icon library

### Infrastructure
- **Docker** - Temporal server container
- **Google Cloud Firestore** - NoSQL database
- **Temporal** - Workflow engine

---

## 🌊 Data Flow Examples

### Example 1: Company Search

```
User: "metlife" 
  ↓
Frontend: POST /api/search { query: "metlife" }
  ↓
Backend: CompanySearchWorkflow
  ↓
Activity: search_companies()
  ↓
Gemini 2.0 Flash:
  - Uses web search grounding
  - Returns top 3 matches
  - JSON format with name, description, industry, etc.
  ↓
Backend: Stores in Firestore session.company_list
  ↓
Response: { mode: "company_list", companies: [...] }
  ↓
Frontend: Renders as cards with "Select" buttons
```

### Example 2: RAG-Enhanced Prediction

```
User: Clicks "Get AI Suggestions" on question BS_Q1
  ↓
Frontend: POST /api/questionnaire/predict-single
  {
    question_id: "BS_Q1",
    company_data: {...},
    configuration: {...}
  }
  ↓
Backend: predict_single_question_with_rag()
  ↓
RAG Filter: should_use_rag(BS_Q1, "How should accounts...")
  → Result: use_rag = true (technical question)
  ↓
RAG Client: POST localhost:5000/api/retrieve
  {
    query: "AWS multi-account best practices for insurance",
    top_k: 5
  }
  ↓
RAG API: 
  - Searches 30K+ AWS document chunks
  - Returns 5 most relevant
  ↓
Backend: Builds prompt:
  - Company: MetLife
  - Industry: Financial Services
  - Compliance: SOX, GLBA, GDPR
  - RAG Docs: [5 AWS best practice chunks]
  - Previous Answers: [context from earlier questions]
  ↓
Gemini 2.0 Flash (temp=0.4):
  - Analyzes all context
  - Generates prediction
  - Provides reasoning with sources
  ↓
Response: 
  {
    prediction: "Multi-Account",
    reasoning: "✅ Based on Retrieved AWS Documentation:\n...",
    confidence: "high",
    rag_used: true
  }
  ↓
Frontend: 
  - Pre-fills answer
  - Shows green checkmark
  - Displays reasoning below
  - User can accept/modify
```

### Example 3: Final Report Generation

```
User: Clicks "Submit & Generate Report"
  ↓
Frontend: POST /api/questionnaire/submit
  {
    session_id: "...",
    answers: { BS_Q1: "...", BS_Q2: "...", ... },  // 114 answers
    company_data: {...},
    configuration: {...}
  }
  ↓
Backend: Loads appropriate Questions.json (AWS/Azure)
  ↓
Gemini Deep Search (gemini-2.0-flash-thinking-exp-1219):
  - Temperature: 0.4 (precise)
  - Max tokens: 8192
  - Input: All 114 answers + company context
  - Task: Generate comprehensive architecture report
  ↓
AI Generates:
  1. Executive Summary
  2. Business Structure (account strategy)
  3. Compliance & Security
  4. Network Architecture
  5. Disaster Recovery
  6. Logging & Audit
  7. Recommendations
  ↓
Backend: Saves to Firestore session.questionnaire_summary
  ↓
Response: { summary: "Full markdown report...", model_used: "..." }
  ↓
Frontend: Displays full report with sections
```

---

## 🧩 Key Components Explained

### 1. **RAG Filter** (`services/rag_filter.py`)

**Purpose**: Decides which questions need AWS documentation

**Logic**:
- Section-based: CL (Compliance), NW (Network), DR (DR) → RAG enabled
- Keyword-based: "security", "encryption", "vpn" → RAG enabled
- Business questions: "How many accounts?" → No RAG (company data sufficient)

**Current Mode**: Testing - forces RAG for ALL questions to validate system

### 2. **Prediction Context** (`services/prediction_context.py`)

**Purpose**: Maintains history of predictions across 114 questions

**Features**:
- Sequential processing (one question at a time)
- Context accumulation (later predictions consider earlier ones)
- RAG source tracking
- Statistics (how many used RAG, confidence levels)

**Example Context**:
```
Question [BS_Q1]: How should AWS accounts be organized?
Selected Answer: Multi-Account
Reasoning: Based on company size (42K employees), regulatory requirements...

Question [BS_Q2]: What's the account naming convention?
Selected Answer: <Region>-<Environment>-<BusinessUnit>
Reasoning: Given the previous Multi-Account selection...
```

### 3. **Firestore Service** (`services/firestore_service.py`)

**Purpose**: All database operations

**Operations**:
- Sessions: CRUD operations
- Messages: Chat history
- Company lists: Store search results
- Configuration: Save/load config
- Questionnaire: Save answers, AI predictions, summaries

**Database**: Google Cloud Firestore (`reqdb`)

### 4. **Temporal Workflows**

**Why Temporal?**
- Reliable workflow execution
- Automatic retries
- Timeout management
- Scalable architecture
- Built-in error handling

**Workflows**:
- `CompanySearchWorkflow` - Orchestrates search
- `CompanyDetailWorkflow` - Orchestrates detail fetch

**Activities**:
- Actual business logic (search, parse, predict)
- Can be retried independently
- Timeout: 10-90 seconds

---

## 📊 Questionnaire Structure

### Questions.json (AWS)

```json
{
  "questions": [
    // Section 1: Business Structure (SEC_BS) - 31 questions
    {
      "id": "SEC_BS",
      "type": "section",
      "label": "Business Structure"
    },
    {
      "id": "BS_Q1",
      "type": "single",
      "question": "How should AWS accounts be organized?",
      "options": [
        { "label": "Multi-Account", "value": "multi" },
        { "label": "Single Account", "value": "single" },
        { "label": "Hybrid", "value": "hybrid" }
      ],
      "metadata": { "category": "account_strategy" }
    },
    
    // Section 2: Compliance (SEC_CL) - 24 questions
    // Section 3: Network (SEC_NW) - 25 questions
    // Section 4: Disaster Recovery (SEC_DR) - 15 questions
    // Section 5: Logging & Audit (SEC_LA) - 13 questions
    // Section 6: Assumptions (SEC_AS) - 6 questions
    
    // Total: 114 questions
  ]
}
```

### Question Types

1. **single** - Radio buttons (one choice)
2. **multi** - Checkboxes (multiple choices)
3. **input** - Text input
4. **section** - Section headers (not answerable)

---

## 🎨 Frontend Features

### App.jsx

**Features**:
- **Two-pane layout**: Sidebar (sessions) + Main content
- **Collapsible sidebar**: Smooth animation with Framer Motion
- **Theme toggle**: Dark/Light mode (persisted)
- **Search bar**: Always visible at top
- **Session management**: Create, load, delete sessions
- **Routing**: React Router (/ and /questionnaire/:id)

**Company Cards**:
- Animated entrance (staggered)
- Hover effects
- "Select" button for each card

**Configuration Form**:
- Inline (within chat)
- Dynamic sub-sectors based on industry
- Save status indicators
- "Continue Questionnaire" button

### Questionnaire.jsx

**Features**:
- **Dynamic loading**: AWS vs Azure questions
- **Progress tracker**: Visual progress bar
- **Section navigation**: Jump to sections
- **AI suggestions**: "Get AI Suggestions" button per question
- **Context display**: Shows previous selections
- **RAG indicators**: Green checkmark when RAG used
- **Reasoning display**: Expandable AI justification
- **Auto-save**: Saves progress continuously
- **Report generation**: Submit button at end

---

## 🔧 Configuration Files

### backend/config/settings.py

```python
class Settings(BaseSettings):
    google_api_key: str = "AIzaSyCI09gbgsjwnnk67GAu5Ul4CCICU1iB2Js"
    gemini_model: str = "gemini-2.0-flash-exp"
    temporal_host: str = "localhost:7233"
    temporal_namespace: str = "default"
    temporal_task_queue: str = "company-search-queue"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: list = ["http://localhost:5173", "http://localhost:3000"]
```

### qna/rag_config.json

```json
{
  "rag_enabled_sections": ["SEC_CL", "SEC_NW", "SEC_DR", "SEC_LA"],
  "rag_keywords": ["compliance", "security", "network", "vpn", "encryption"],
  "excluded_questions": [],
  "rag_settings": {
    "top_k": 5,
    "timeout_seconds": 10,
    "retry_attempts": 1
  }
}
```

---

## 🚀 Startup Sequence

### 1. Start Temporal Server (Terminal 1)
```bash
docker-compose up
# Wait for "Started" messages
```

### 2. Start Backend Worker (Terminal 2)
```bash
cd backend
venv\Scripts\Activate.ps1
python worker.py
# Wait for "Worker started successfully"
```

### 3. Start Backend API (Terminal 3)
```bash
cd backend
venv\Scripts\Activate.ps1
python app.py
# Wait for "Uvicorn running on http://0.0.0.0:8000"
```

### 4. Start Frontend (Terminal 4)
```bash
cd frontend
npm run dev
# Wait for "Local: http://localhost:5173"
```

### 5. (Optional) Start RAG API (Terminal 5)
```bash
cd [RAG project directory]
python api.py
# Wait for "Running on http://localhost:5000"
```

---

## 🧪 Testing Checklist

- [ ] Health check: `curl http://localhost:8000/health`
- [ ] Company search: Search "MetLife"
- [ ] Company selection: Select company #1
- [ ] Configuration form: Review AI-generated values
- [ ] Save config: Click "Continue Questionnaire"
- [ ] Load questionnaire: Verify 114 questions loaded
- [ ] AI prediction: Click "Get AI Suggestions" on BS_Q1
- [ ] RAG verification: Check green checkmark and reasoning
- [ ] Complete questionnaire: Fill out all sections
- [ ] Generate report: Click "Submit & Generate Report"
- [ ] View report: Verify comprehensive markdown output

---

## 📈 Performance Metrics

| Operation | Expected Time | Notes |
|-----------|--------------|-------|
| Company search | 5-10s | Gemini web search |
| Company details | 10-15s | Gemini detailed fetch |
| Config inference | 3-5s | AI analysis |
| Single prediction (no RAG) | 2-3s | Gemini only |
| Single prediction (with RAG) | 5-8s | RAG retrieval + Gemini |
| Report generation | 15-30s | Deep thinking model |

---

## 🐛 Common Issues

### Issue: Temporal connection failed
**Solution**: Ensure Docker is running and Temporal container is up

### Issue: Firestore permission denied
**Solution**: Check `reqagent-c12e92ab61f5.json` credentials file exists

### Issue: RAG API not found
**Solution**: Start RAG API separately: `python api.py` in RAG project

### Issue: Questionnaire not loading
**Solution**: Check `qna/Questions.json` exists and is valid JSON

### Issue: AI predictions timeout
**Solution**: Increase timeout in activities (currently 60-90s)

---

## 🔮 Future Enhancements

### Phase 1 (In Progress)
- [x] Two-stage company search
- [x] AI configuration inference
- [x] RAG-enhanced predictions
- [x] Context accumulation
- [x] Deep thinking report generation

### Phase 2 (Planned)
- [ ] Multi-cloud support (GCP)
- [ ] Custom questionnaire builder
- [ ] Report templates
- [ ] Export to Word/PDF
- [ ] Team collaboration

### Phase 3 (Future)
- [ ] Real-time collaboration
- [ ] Version control for answers
- [ ] Approval workflows
- [ ] API for external integrations
- [ ] Mobile app

---

## 📚 Related Documentation

1. **README.md** - Main setup guide
2. **PROJECT_SUMMARY.md** - High-level overview
3. **FEATURE_GUIDE.md** - Two-stage search details
4. **RAG_INTEGRATION.md** - RAG API integration
5. **SETUP_GUIDE.md** - Detailed setup instructions
6. **START_HERE.md** - Quick start guide

---

## 🤝 Contributing

This project follows:
- **PEP8** for Python code (enforced by Black, isort, flake8)
- **ESLint** for JavaScript/React code
- **Conventional Commits** for commit messages

---

## 📄 License

MIT License - Feel free to use and modify

---

**Last Updated**: October 29, 2025
**Version**: 1.0.0
**Status**: Production Ready
