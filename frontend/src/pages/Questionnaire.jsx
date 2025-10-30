import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import axios from 'axios';
import awsQuestionsData from '../../../qna/Questions.json';
import azureQuestionsData from '../../../qna/questionsazure.json';
import './Questionnaire.css';

const API_BASE_URL = 'http://localhost:8000';

function Questionnaire() {
  const { sessionId } = useParams();
  const navigate = useNavigate();

  // State
  const [questions, setQuestions] = useState([]);
  const [answers, setAnswers] = useState({});
  const [aiPredictions, setAiPredictions] = useState({});
  const [aiAssumptions, setAiAssumptions] = useState({});
  const [expandedAssumptions, setExpandedAssumptions] = useState({});
  const [visibleQuestions, setVisibleQuestions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [analyzing, setAnalyzing] = useState(false);
  const [generatingSummary, setGeneratingSummary] = useState(false);
  const [companyData, setCompanyData] = useState(null);
  const [configData, setConfigData] = useState(null);
  const [error, setError] = useState(null);

  // RAG Enhancement State
  const [useRag, setUseRag] = useState(true); // RAG enabled by default
  const [processingProgress, setProcessingProgress] = useState({
    current: 0,
    total: 0,
    questionId: null,
    isProcessing: false
  });
  const [ragMetadata, setRagMetadata] = useState({}); // Store RAG info per question

  // Section-Based Workflow State
  const [workflowMode, setWorkflowMode] = useState('section-based'); // 'per-question' or 'section-based'
  const [workflowId, setWorkflowId] = useState(null);
  const [workflowStatus, setWorkflowStatus] = useState(null); // 'running', 'completed', 'failed', 'cancelled'
  const [sectionProgress, setSectionProgress] = useState({
    sections_completed: 0,
    total_sections: 0,
    predictions_made: 0,
    current_section: null
  });
  const [pollingInterval, setPollingInterval] = useState(null);

  // Load company info and configuration on mount
  useEffect(() => {
    loadSessionData();
  }, [sessionId]);

  // Load appropriate questions based on cloud provider
  useEffect(() => {
    if (configData?.cloud_provider) {
      loadQuestionsByProvider(configData.cloud_provider);
    }
  }, [configData]);

  // Compute visible questions whenever answers change
  useEffect(() => {
    if (questions.length > 0) {
      computeVisibleQuestions();
    }
  }, [answers, questions]);

  // Note: Auto-trigger removed - user must manually start analysis via button
  // This prevents unwanted automatic processing on page load

  const loadQuestionsByProvider = (provider) => {
    let questionsToLoad = [];

    if (provider === 'Azure') {
      // Load Azure questions - flatten sections into questions array
      if (azureQuestionsData.sections) {
        azureQuestionsData.sections.forEach((section) => {
          // Add section as a header
          questionsToLoad.push({
            id: `section_${section.title}`,
            type: 'section',
            title: section.title
          });
          // Add all questions from this section
          questionsToLoad.push(...section.questions.map(q => ({
            ...q,
            question: q.text, // Map 'text' to 'question' for consistency
            type: 'single' // Azure questions are single-choice based on the structure
          })));
        });
      }
    } else {
      // Default to AWS questions
      questionsToLoad = awsQuestionsData.questions || [];
    }

    setQuestions(questionsToLoad);
  };

  const loadSessionData = async () => {
    try {
      setLoading(true);
      setError(null);

      // Load session messages to get company info
      const sessionResponse = await axios.get(`${API_BASE_URL}/api/sessions/${sessionId}`);

      // Find the detailed company info from messages
      const messages = sessionResponse.data.messages || [];
      const detailedMessage = messages.find(
        msg => msg.role === 'assistant' && msg.content?.mode === 'detailed_info'
      );

      if (!detailedMessage) {
        setError('No company information found. Please complete the company search first.');
        return;
      }

      setCompanyData(detailedMessage.content.data);

      // Load configuration
      const configResponse = await axios.get(`${API_BASE_URL}/api/sessions/${sessionId}/config`);
      setConfigData(configResponse.data.configuration);

      // Load any saved questionnaire answers
      try {
        const answersResponse = await axios.get(
          `${API_BASE_URL}/api/sessions/${sessionId}/questionnaire`
        );
        if (answersResponse.data.answers) {
          setAnswers(answersResponse.data.answers);
        }
        if (answersResponse.data.ai_predictions) {
          setAiPredictions(answersResponse.data.ai_predictions);
        }
        if (answersResponse.data.ai_assumptions) {
          setAiAssumptions(answersResponse.data.ai_assumptions);
        }
      } catch (err) {
        // No saved answers yet, that's okay
        console.log('No saved questionnaire data');
      }

    } catch (err) {
      console.error('Error loading session data:', err);
      setError('Failed to load session data. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (pollingInterval) {
        clearInterval(pollingInterval);
      }
    };
  }, [pollingInterval]);

  // Start section-based workflow analysis
  const startWorkflowAnalysis = async () => {
    try {
      setAnalyzing(true);
      setWorkflowStatus('running');
      setError(null);

      // Start the workflow
      const response = await axios.post(`${API_BASE_URL}/api/questionnaire/analyze`, {
        session_id: sessionId,
        company_data: companyData,
        configuration: configData
      });

      const { workflow_id } = response.data;
      setWorkflowId(workflow_id);

      // Start polling for progress
      const interval = setInterval(() => pollWorkflowProgress(workflow_id), 2000);
      setPollingInterval(interval);

    } catch (err) {
      console.error('Error starting workflow:', err);
      setError('Failed to start analysis workflow. Please try again.');
      setAnalyzing(false);
      setWorkflowStatus('failed');
    }
  };

  // Poll workflow progress
  const pollWorkflowProgress = async (wfId) => {
    try {
      const response = await axios.get(
        `${API_BASE_URL}/api/questionnaire/progress/${wfId}`
      );

      const { status, progress, results } = response.data;

      // Update progress
      if (progress) {
        setSectionProgress({
          sections_completed: progress.sections_completed || 0,
          total_sections: progress.total_sections || 0,
          predictions_made: progress.predictions_made || 0,
          current_section: progress.current_section || null
        });
      }

      // Update workflow status
      setWorkflowStatus(status);

      // If workflow completed, stop polling and load results
      if (status === 'completed' || status === 'failed' || status === 'cancelled') {
        if (pollingInterval) {
          clearInterval(pollingInterval);
          setPollingInterval(null);
        }
        setAnalyzing(false);

        // Load the predictions if completed successfully
        if (status === 'completed' && results) {
          const { predictions, reasoning, rag_metadata } = results;

          // Apply predictions to answers
          const newAnswers = { ...answers };
          const newPredictions = {};
          const newAssumptions = {};
          const newRagMetadata = {};

          Object.entries(predictions || {}).forEach(([qId, prediction]) => {
            newAnswers[qId] = prediction;
            newPredictions[qId] = prediction;
            if (reasoning && reasoning[qId]) {
              newAssumptions[qId] = reasoning[qId];
            }
          });

          // Process RAG metadata from section-based workflow
          // The format is: rag_metadata = { "SEC_BS": { retrieval_time, total_chunks, sources, ... }, ... }
          // We need to map this to individual questions based on their section
          if (rag_metadata) {
            Object.keys(predictions || {}).forEach(qId => {
              // Determine which section this question belongs to
              const sectionPrefix = qId.split('_')[0]; // e.g., "BS" from "BS_Q1"
              const sectionKey = `SEC_${sectionPrefix}`; // e.g., "SEC_BS"

              if (rag_metadata[sectionKey]) {
                const sectionRag = rag_metadata[sectionKey];
                newRagMetadata[qId] = {
                  ragUsed: !sectionRag.error, // If no error, RAG was used
                  ragSources: sectionRag.sources || [],
                  retrievalTime: sectionRag.retrieval_time,
                  totalChunks: sectionRag.total_chunks
                };
              }
            });
          }

          setAnswers(newAnswers);
          setAiPredictions(prev => ({ ...prev, ...newPredictions }));
          setAiAssumptions(prev => ({ ...prev, ...newAssumptions }));
          setRagMetadata(prev => ({ ...prev, ...newRagMetadata }));

          // Expand all assumptions
          const newExpanded = {};
          Object.keys(predictions || {}).forEach(qId => {
            newExpanded[qId] = true;
          });
          setExpandedAssumptions(prev => ({ ...prev, ...newExpanded }));

          await saveProgress(newAnswers, newPredictions, newAssumptions);
        }
      }
    } catch (err) {
      console.error('Error polling workflow progress:', err);
    }
  };

  // Cancel workflow
  const cancelWorkflow = async () => {
    if (!workflowId) return;

    try {
      await axios.post(`${API_BASE_URL}/api/questionnaire/cancel/${workflowId}`);

      if (pollingInterval) {
        clearInterval(pollingInterval);
        setPollingInterval(null);
      }

      setWorkflowStatus('cancelled');
      setAnalyzing(false);
    } catch (err) {
      console.error('Error cancelling workflow:', err);
      setError('Failed to cancel workflow.');
    }
  };

  const computeVisibleQuestions = () => {
    const visible = [];
    const visited = new Set();

    const traverse = (questionId) => {
      if (!questionId || visited.has(questionId)) return;
      visited.add(questionId);

      const question = questions.find((q) => q.id === questionId);
      if (!question) return;

      visible.push(questionId);

      // For sections, just add them and move on
      if (question.type === 'section') {
        return;
      }

      // Check if this question has a selected answer
      const answer = answers[questionId];

      if (question.type === 'single' && answer) {
        // Find the selected option
        const selectedOption = question.options?.find(opt =>
          opt.label === answer || opt.value === answer
        );
        if (selectedOption?.next) {
          selectedOption.next.forEach(traverse);
        }
      } else if (question.type === 'multi' && Array.isArray(answer) && answer.length > 0) {
        // For multi-select, check all selected options for next questions
        const selectedOptions = question.options?.filter(opt =>
          answer.includes(opt.label) || answer.includes(opt.value)
        ) || [];
        selectedOptions.forEach(opt => {
          if (opt.next) {
            opt.next.forEach(traverse);
          }
        });
      } else if (question.type === 'input' && answer) {
        // Input questions can have next
        if (question.next) {
          question.next.forEach(traverse);
        }
      }

      // If question has unconditional next (not tied to options), traverse them
      if (question.next && (question.type === 'input' || question.type === 'section')) {
        question.next.forEach(traverse);
      }
    };

    // Start with root questions (those not referenced in any 'next' or those marked with show: true)
    const allNextIds = new Set();
    questions.forEach((q) => {
      if (q.next) {
        q.next.forEach(id => allNextIds.add(id));
      }
      if (q.options) {
        q.options.forEach(opt => {
          if (opt.next) {
            opt.next.forEach(id => allNextIds.add(id));
          }
        });
      }
    });

    // For Azure questions, also check the 'show' property and 'parent' property
    const rootQuestions = questions.filter(q => {
      // Sections are always root
      if (q.type === 'section') return true;

      // Questions with show: true and no parent are root
      if (q.show === true && !q.parent) return true;

      // Questions not referenced in any 'next' are root
      if (!allNextIds.has(q.id) && q.show !== false) return true;

      return false;
    });

    rootQuestions.forEach(q => traverse(q.id));

    setVisibleQuestions(visible);
  };

  const performAIAnalysis = async (questionIds) => {
    if (analyzing) return;

    try {
      setAnalyzing(true);
      setProcessingProgress({
        current: 0,
        total: questionIds.length,
        questionId: null,
        isProcessing: true
      });

      const newAnswers = { ...answers };
      const newPredictions = {};
      const newAssumptions = {};
      const newRagMetadata = { ...ragMetadata };

      // Process EACH question sequentially
      for (let i = 0; i < questionIds.length; i++) {
        const questionId = questionIds[i];

        // Update progress
        setProcessingProgress({
          current: i + 1,
          total: questionIds.length,
          questionId: questionId,
          isProcessing: true
        });

        // Find question details
        const question = questions.find(q => q.id === questionId);
        if (!question || question.type === 'section') continue;

        try {
          let prediction, reasoning, ragUsed, ragSources;

          if (useRag) {
            // RAG-ENHANCED MODE: Call single question endpoint
            const response = await axios.post(
              `${API_BASE_URL}/api/questionnaire/predict-single`,
              {
                session_id: sessionId,
                question_id: questionId,
                company_data: companyData,
                configuration: configData
              }
            );

            const result = response.data;
            prediction = result.prediction;
            reasoning = result.reasoning;
            ragUsed = result.rag_used;
            ragSources = result.rag_sources || [];

            // Store RAG metadata for this question
            newRagMetadata[questionId] = {
              ragUsed: ragUsed,
              ragSources: ragSources,
              retrievalTime: result.rag_metadata?.retrieval_time,
              confidence: result.confidence
            };

          } else {
            // LEGACY MODE: Use batch endpoint for this single question
            const response = await axios.post(
              `${API_BASE_URL}/api/questionnaire/predict`,
              {
                session_id: sessionId,
                question_ids: [questionId],
                company_data: companyData,
                configuration: configData,
                current_answers: newAnswers
              }
            );

            const result = response.data;
            prediction = result.predictions?.[questionId];
            reasoning = result.assumptions?.[questionId];
            ragUsed = false;
            ragSources = [];
          }

          // Apply prediction if valid
          if (prediction && !answers[questionId]) {
            newAnswers[questionId] = prediction;
            newPredictions[questionId] = prediction;
            newAssumptions[questionId] = reasoning;
          }

        } catch (error) {
          console.error(`Error predicting question ${questionId}:`, error);
          newAssumptions[questionId] = `⚠️ Prediction failed: ${error.message}`;
        }

        // Small delay between questions for better UX
        await new Promise(resolve => setTimeout(resolve, 100));
      }

      // Update all states at once after processing
      setAnswers(newAnswers);
      setAiPredictions(prev => ({ ...prev, ...newPredictions }));
      setAiAssumptions(prev => ({ ...prev, ...newAssumptions }));
      setRagMetadata(newRagMetadata);

      // Expand assumptions by default
      const newExpanded = { ...expandedAssumptions };
      questionIds.forEach(qId => {
        newExpanded[qId] = true;
      });
      setExpandedAssumptions(newExpanded);

      // Save progress
      await saveProgress(newAnswers, newPredictions, newAssumptions);

    } catch (err) {
      console.error('Error performing AI analysis:', err);
    } finally {
      setAnalyzing(false);
      setProcessingProgress({
        current: 0,
        total: 0,
        questionId: null,
        isProcessing: false
      });
    }
  };

  const saveProgress = async (currentAnswers, currentPredictions, currentAssumptions) => {
    try {
      await axios.post(`${API_BASE_URL}/api/questionnaire/save`, {
        session_id: sessionId,
        answers: currentAnswers,
        ai_predictions: currentPredictions,
        ai_assumptions: currentAssumptions,
      });
    } catch (err) {
      console.error('Error saving progress:', err);
    }
  };

  const handleAnswerChange = (questionId, value, isMulti = false) => {
    const question = questions.find(q => q.id === questionId);
    const oldAnswer = answers[questionId];

    // Update answer
    const newAnswers = { ...answers };

    if (isMulti) {
      const currentValues = newAnswers[questionId] || [];
      if (currentValues.includes(value)) {
        // Remove if already selected
        newAnswers[questionId] = currentValues.filter(v => v !== value);
      } else {
        // Add to selection
        newAnswers[questionId] = [...currentValues, value];
      }
    } else {
      newAnswers[questionId] = value;
    }

    // Check if answer changed in a way that affects child questions
    const answerChanged = JSON.stringify(oldAnswer) !== JSON.stringify(newAnswers[questionId]);

    if (answerChanged) {
      // Find all questions that should be cleared (children of this question)
      const questionsToCheck = [questionId];
      const childQuestions = new Set();

      while (questionsToCheck.length > 0) {
        const currentQId = questionsToCheck.shift();
        const currentQ = questions.find(q => q.id === currentQId);

        if (!currentQ) continue;

        // Get next questions from this question
        const nextQIds = [];
        if (currentQ.next) {
          nextQIds.push(...currentQ.next);
        }
        if (currentQ.options) {
          currentQ.options.forEach(opt => {
            if (opt.next) {
              nextQIds.push(...opt.next);
            }
          });
        }

        nextQIds.forEach(qId => {
          if (!childQuestions.has(qId)) {
            childQuestions.add(qId);
            questionsToCheck.push(qId);
          }
        });
      }

      // Clear answers for child questions
      childQuestions.forEach(qId => {
        delete newAnswers[qId];
      });
    }

    setAnswers(newAnswers);
    saveProgress(newAnswers, aiPredictions, aiAssumptions);
  };

  const toggleAssumption = (questionId) => {
    setExpandedAssumptions(prev => ({
      ...prev,
      [questionId]: !prev[questionId]
    }));
  };

  const handleSubmit = async () => {
    try {
      setGeneratingSummary(true);
      setError(null);

      const response = await axios.post(`${API_BASE_URL}/api/questionnaire/submit`, {
        session_id: sessionId,
        answers: answers,
        company_data: companyData,
        configuration: configData,
      });

      // Navigate to summary or show summary in modal
      alert('Questionnaire submitted successfully! Summary will be generated.');
      console.log('Summary:', response.data.summary);

    } catch (err) {
      console.error('Error submitting questionnaire:', err);
      setError('Failed to submit questionnaire. Please try again.');
    } finally {
      setGeneratingSummary(false);
    }
  };

  const renderQuestion = (questionId) => {
    const question = questions.find(q => q.id === questionId);
    if (!question) return null;

    // Render section headers
    if (question.type === 'section') {
      return (
        <div key={question.id} className="question-section-header">
          <h2>{question.title}</h2>
        </div>
      );
    }

    const hasAssumption = aiAssumptions[questionId];
    const isExpanded = expandedAssumptions[questionId] !== false; // Default expanded

    return (
      <div key={question.id} className="question-card">
        {/* RAG Source Indicator */}
        {ragMetadata[question.id]?.ragUsed && (
          <div className="rag-sources-indicator">
            <div className="rag-sources-header">
              <span className="rag-icon">📄</span>
              <span className="rag-label">Based on AWS Documentation:</span>
            </div>
            <div className="rag-sources-list">
              {ragMetadata[question.id].ragSources.map((source, idx) => (
                <span key={idx} className="rag-source-badge">
                  {source}
                </span>
              ))}
            </div>
            {ragMetadata[question.id].retrievalTime && (
              <div className="rag-retrieval-time-only">
                ⏱️ {ragMetadata[question.id].retrievalTime.toFixed(2)}s
              </div>
            )}
          </div>
        )}

        {/* AI Assumptions Dropdown */}
        {hasAssumption && (
          <div className="ai-assumptions">
            <button
              className="assumptions-toggle"
              onClick={() => toggleAssumption(question.id)}
            >
              <span className="toggle-icon">{isExpanded ? '▼' : '▶'}</span>
              <span className="toggle-label">AI Assumptions</span>
            </button>
            {isExpanded && (
              <div className="assumptions-content">
                <p>{aiAssumptions[question.id]}</p>
              </div>
            )}
          </div>
        )}

        {/* Question */}
        <div className="question-content">
          <h3 className="question-text">{question.question}</h3>

          {/* Single choice */}
          {question.type === 'single' && (
            <div className="options-container">
              {question.options.map((option, idx) => {
                const optionValue = option.value || option.label;
                const optionLabel = option.label;
                return (
                  <label key={idx} className="option-label radio-option">
                    <input
                      type="radio"
                      name={question.id}
                      value={optionValue}
                      checked={answers[question.id] === optionValue || answers[question.id] === optionLabel}
                      onChange={(e) => handleAnswerChange(question.id, e.target.value)}
                    />
                    <span>{optionLabel}</span>
                  </label>
                );
              })}
            </div>
          )}

          {/* Multiple choice */}
          {question.type === 'multi' && (
            <div className="options-container">
              {question.options.map((option, idx) => {
                const optionValue = option.value || option.label;
                const optionLabel = option.label;
                return (
                  <label key={idx} className="option-label checkbox-option">
                    <input
                      type="checkbox"
                      value={optionValue}
                      checked={(answers[question.id] || []).includes(optionValue) || (answers[question.id] || []).includes(optionLabel)}
                      onChange={() => handleAnswerChange(question.id, optionValue, true)}
                    />
                    <span>{optionLabel}</span>
                  </label>
                );
              })}
            </div>
          )}

          {/* Input */}
          {question.type === 'input' && (
            <input
              type="text"
              className="text-input"
              value={answers[question.id] || ''}
              onChange={(e) => handleAnswerChange(question.id, e.target.value)}
              placeholder="Enter your answer..."
            />
          )}
        </div>
      </div>
    );
  };

  if (loading) {
    return (
      <div className="questionnaire-loading">
        <div className="loading-spinner"></div>
        <p>Loading questionnaire...</p>
      </div>
    );
  }

  if (generatingSummary) {
    return (
      <div className="questionnaire-loading">
        <div className="loading-spinner"></div>
        <p>Generating summary...</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="questionnaire-error">
        <h2>Error</h2>
        <p>{error}</p>
        <button onClick={() => navigate('/')} className="back-button">
          Back to Chat
        </button>
      </div>
    );
  }

  return (
    <div className="questionnaire-container">
      <div className="questionnaire-header">
        <h1>Landing Zone Questionnaire</h1>
        <p className="company-info-header">
          {companyData?.['Company name']} - {configData?.cloud_provider}
        </p>
        <button onClick={() => navigate('/')} className="back-link">
          ← Back to Chat
        </button>
      </div>

      <div className="questionnaire-content">
        {/* Analysis Mode Selector */}
        <div className="analysis-mode-selector">
          <h3>Analysis Mode</h3>
          <div className="mode-options">
            <label className="mode-option">
              <input
                type="radio"
                value="section-based"
                checked={workflowMode === 'section-based'}
                onChange={(e) => setWorkflowMode(e.target.value)}
                disabled={workflowStatus === 'running'}
              />
              <div className="mode-details">
                <span className="mode-title">🚀 Section-Based Workflow (Recommended)</span>
                <span className="mode-description">
                  Process all sections at once with batch predictions. 54% faster with context accumulation across sections.
                </span>
              </div>
            </label>
            <label className="mode-option">
              <input
                type="radio"
                value="per-question"
                checked={workflowMode === 'per-question'}
                onChange={(e) => setWorkflowMode(e.target.value)}
                disabled={workflowStatus === 'running'}
              />
              <div className="mode-details">
                <span className="mode-title">⚡ Per-Question Mode (Legacy)</span>
                <span className="mode-description">
                  Process questions one-by-one as they appear. Good for incremental progress.
                </span>
              </div>
            </label>
          </div>
        </div>

        {/* Section-Based Workflow Controls */}
        {workflowMode === 'section-based' && (
          <div className="workflow-controls">
            {!workflowStatus || workflowStatus === 'cancelled' || workflowStatus === 'failed' ? (
              <button
                onClick={startWorkflowAnalysis}
                className="start-workflow-button"
                disabled={analyzing || !companyData || !configData}
              >
                Start Analysis
              </button>
            ) : null}

            {workflowStatus === 'running' && (
              <div className="workflow-progress-container">
                <div className="workflow-progress-header">
                  <span className="progress-title">Processing Sections...</span>
                  <button
                    onClick={cancelWorkflow}
                    className="cancel-workflow-button"
                  >
                    ✕ Cancel
                  </button>
                </div>
                <div className="section-progress-bar">
                  <div
                    className="section-progress-fill"
                    style={{
                      width: `${sectionProgress.total_sections > 0
                        ? (sectionProgress.sections_completed / sectionProgress.total_sections) * 100
                        : 0}%`
                    }}
                  />
                </div>
                <div className="section-progress-details">
                  <span>
                    Section {sectionProgress.sections_completed} of {sectionProgress.total_sections}
                  </span>
                  <span>
                    {sectionProgress.predictions_made} predictions made
                  </span>
                </div>
                {sectionProgress.current_section && (
                  <div className="current-section-indicator">
                    Processing: {sectionProgress.current_section}
                  </div>
                )}
              </div>
            )}

            {workflowStatus === 'completed' && (
              <div className="workflow-status-message success">
                ✅ Analysis completed! {sectionProgress.predictions_made} predictions made across {sectionProgress.sections_completed} sections.
              </div>
            )}

            {workflowStatus === 'failed' && (
              <div className="workflow-status-message error">
                ❌ Workflow failed. Please try again or switch to per-question mode.
              </div>
            )}

            {workflowStatus === 'cancelled' && (
              <div className="workflow-status-message warning">
                ⚠️ Analysis was cancelled. You can restart or switch to per-question mode.
              </div>
            )}
          </div>
        )}

        {/* RAG Enhancement Toggle (shown for both modes, always enabled for section-based) */}
        <div className="rag-toggle-container">
          <label className="rag-toggle-label">
            <input
              type="checkbox"
              checked={true}
              onChange={(e) => {}}
              className="rag-toggle-checkbox"
              disabled={true}
            />
            <span className="rag-toggle-text">
              ✨ Use RAG Enhancement
              <span className="rag-toggle-description">
                (AI will consult AWS documentation for technical questions)
              </span>
            </span>
          </label>
        </div>

        {/* Progress Indicator */}
        {processingProgress.isProcessing && (
          <div className="progress-indicator">
            <div className="progress-bar-container">
              <div
                className="progress-bar-fill"
                style={{
                  width: `${(processingProgress.current / processingProgress.total) * 100}%`
                }}
              />
            </div>
            <div className="progress-text">
              {useRag ? '🔍 Analyzing' : '⚡ Processing'} question {processingProgress.current} of {processingProgress.total}
              {processingProgress.questionId && ` (${processingProgress.questionId})`}
            </div>
          </div>
        )}

        <div className="questions-list">
          {visibleQuestions.map(renderQuestion)}
        </div>

        <div className="questionnaire-footer">
          <button
            onClick={handleSubmit}
            className="submit-button"
            disabled={loading || analyzing || generatingSummary}
          >
            Submit & Generate Summary
          </button>
        </div>
      </div>
    </div>
  );
}

export default Questionnaire;
