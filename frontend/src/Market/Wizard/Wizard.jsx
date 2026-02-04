// src/pages/Wizard/Wizard.jsx
import React, { useState, useEffect, useRef } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import './Wizard.css';

const Wizard = () => {
  const navigate = useNavigate();
  const location = useLocation();
  const chatHistoryRef = useRef(null);
  
  // Get source from URL params
  const urlParams = new URLSearchParams(location.search);
  const sourceParam = urlParams.get('source') || 'market_analysis';
  
  // State management
  const [currentDocType, setCurrentDocType] = useState(sourceParam);
  const [currentPhase, setCurrentPhase] = useState(1);
  const [detailedMode, setDetailedMode] = useState(true);
  const [chatHistory, setChatHistory] = useState([]);
  const [userInput, setUserInput] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [enterToSend, setEnterToSend] = useState(true);
  const [sessionId, setSessionId] = useState(null);
  const [hasSaved, setHasSaved] = useState(false);
  const [activeNotesTab, setActiveNotesTab] = useState('phase1');
  const [notes, setNotes] = useState({
    phase1: '',
    phase2: '',
    phase3: ''
  });
  const [showFinishModal, setShowFinishModal] = useState(false);

  // Document phases configuration
  const documentPhases = {
    market_analysis: [
      { title: 'Market Overview', description: 'Analyze the market landscape for your new product or service.' },
      { title: 'Competitive Analysis', description: 'Evaluate competitors and identify your unique value proposition.' },
      { title: 'Go-to-Market Strategy', description: 'Develop a strategy for launching and marketing your product/service.' }
    ],
    gap_analysis: [
      { title: 'Current State Assessment', description: 'Evaluate the current state of your existing product or service.' },
      { title: 'Desired Future State', description: 'Define the ideal future state for your product or service.' },
      { title: 'Gap Identification & Action Plan', description: 'Identify gaps between current and desired states and create an action plan.' }
    ],
    swot_analysis: [
      { title: 'Identify Strengths', description: 'Gather information on internal strengths of your organization or product.' },
      { title: 'Identify Weaknesses', description: 'Examine internal weaknesses or areas of improvement.' },
      { title: 'Opportunities & Threats', description: 'Identify external opportunities and threats, then summarize the SWOT.' }
    ]
  };

  // Welcome messages for each analysis type
  const welcomeMessages = {
    market_analysis: {
      title: 'Welcome to the Market Analysis Wizard!',
      subtitle: "I'll help you analyze the market for your new product or service.",
      question: 'What product or service are you considering launching?'
    },
    gap_analysis: {
      title: 'Welcome to the Gap Analysis Wizard!',
      subtitle: "I'll help you identify gaps and improvements for your existing product or service.",
      question: 'What existing product or service would you like to improve?'
    },
    swot_analysis: {
      title: 'Welcome to the SWOT Analysis Wizard!',
      subtitle: "I'll help you assess Strengths, Weaknesses, Opportunities, and Threats.",
      question: 'What organization or product do you want to analyze?'
    }
  };

  // Initialize chat with welcome message
  useEffect(() => {
    const welcome = welcomeMessages[currentDocType];
    setChatHistory([{
      type: 'system',
      content: `
        <div class="welcome-message">
          <p><strong>${welcome.title}</strong></p>
          <p>${welcome.subtitle}</p>
          <p>${welcome.question}</p>
        </div>
      `
    }]);
    setCurrentPhase(1);
    setActiveNotesTab('phase1');
  }, [currentDocType]);

  // Auto-scroll chat to bottom
  useEffect(() => {
    if (chatHistoryRef.current) {
      chatHistoryRef.current.scrollTop = chatHistoryRef.current.scrollHeight;
    }
  }, [chatHistory]);

  // Handle document type change
  const handleDocTypeChange = (newType) => {
    if (chatHistory.length > 1) {
      if (!window.confirm('Changing the document type will reset your current session. Are you sure?')) {
        return;
      }
    }
    setCurrentDocType(newType);
    setCurrentPhase(1);
    setNotes({ phase1: '', phase2: '', phase3: '' });
    setSessionId(null);
    setHasSaved(false);
  };

  // Handle chat submission
  const handleSubmit = async () => {
    if (!userInput.trim() || isLoading) return;

    const message = userInput.trim();
    setUserInput('');
    
    // Add user message to chat
    setChatHistory(prev => [...prev, {
      type: 'user',
      content: message
    }]);

    setIsLoading(true);

    try {
      const response = await fetch('https://api.sekki.io/api/ai-agent/conversation/continue', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        },
        body: JSON.stringify({
          message,
          docType: currentDocType,
          detailed: detailedMode,
          phase: currentPhase,
          systemPrompt: getSystemPrompt()
        })
      });

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }

      const data = await response.json();
      
      if (data.reply) {
        // Process the reply for better formatting
        let processedText = data.reply;
        processedText = processedText.replace(/\*\*([^*]+)\*\*/g, '$1');
        processedText = processedText.replace(/(\d+\.\s)/g, '\n\n$1');
        processedText = processedText.replace(/([^:\n]+:)(\s*\n)/g, '$1\n\n');
        processedText = processedText.replace(/\n{3,}/g, '\n\n');

        const formattedText = processedText
          .split('\n\n')
          .filter(para => para.trim())
          .map(para => {
            const t = para.trim();
            if (/^\d+\./.test(t)) {
              return `<p style="margin-bottom:16px;padding-left:8px;">${t}</p>`;
            }
            return `<p>${t}</p>`;
          })
          .join('');

        setChatHistory(prev => [...prev, {
          type: 'system',
          content: formattedText
        }]);
      }
    } catch (error) {
      console.error('Chat error:', error);
      setChatHistory(prev => [...prev, {
        type: 'system',
        content: `<p>I apologize, an error occurred: ${error.message}</p>`
      }]);
    } finally {
      setIsLoading(false);
    }
  };

  // Get system prompt based on current phase and mode
  const getSystemPrompt = () => {
    // This would contain the detailed system prompts from the WordPress version
    // For now, returning a basic prompt
    return `You are a top business analyst helping with ${currentDocType.replace('_', ' ')} in phase ${currentPhase}. ${detailedMode ? 'Provide detailed analysis.' : 'Be concise and focused.'}`;
  };

  // Handle keyboard input
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey && enterToSend) {
      e.preventDefault();
      handleSubmit();
    }
  };

  // Phase navigation
  const handlePrevPhase = () => {
    if (currentPhase > 1) {
      setCurrentPhase(currentPhase - 1);
      setActiveNotesTab(`phase${currentPhase - 1}`);
    }
  };

  const handleNextPhase = () => {
    if (currentPhase < 3) {
      setCurrentPhase(currentPhase + 1);
      setActiveNotesTab(`phase${currentPhase + 1}`);
    } else {
      // Handle finish
      handleFinish();
    }
  };

  const handleFinish = async () => {
    // First, force save the session if not already saved
    if (!hasSaved) {
      const sessionTitle = prompt('Enter a session title:', `${currentDocType.replace('_', ' ')} - ${new Date().toLocaleDateString()}`);
      if (!sessionTitle) return; // User cancelled, don't proceed
      
      try {
        const sessionData = {
          session_id: sessionId || `session_${Date.now()}`,
          name: sessionTitle,
          document_type: currentDocType,
          current_phase: currentPhase,
          chat_history: chatHistory,
          notes: notes,
          created: new Date().toISOString(),
          timestamp: new Date().toISOString(),
          status: 'completed' // Mark as completed when finishing
        };

        // Save to localStorage as backup
        localStorage.setItem(`session_${sessionData.session_id}`, JSON.stringify(sessionData));
        
        setSessionId(sessionData.session_id);
        setHasSaved(true);
      } catch (error) {
        console.error('Save error:', error);
        alert('Failed to save session. Please try again.');
        return;
      }
    } else {
      // Update existing session to completed status
      try {
        const existingSession = JSON.parse(localStorage.getItem(`session_${sessionId}`));
        if (existingSession) {
          existingSession.status = 'completed';
          existingSession.timestamp = new Date().toISOString();
          localStorage.setItem(`session_${sessionId}`, JSON.stringify(existingSession));
        }
      } catch (error) {
        console.error('Error updating session status:', error);
      }
    }
    
    // Show the finish modal
    setShowFinishModal(true);
  };

  // Save session
  const handleSaveSession = async () => {
    const sessionTitle = prompt('Enter a session title:', `${currentDocType.replace('_', ' ')} - ${new Date().toLocaleDateString()}`);
    if (!sessionTitle) return;

    try {
      const sessionData = {
        session_id: sessionId || `session_${Date.now()}`,
        name: sessionTitle,
        document_type: currentDocType,
        current_phase: currentPhase,
        chat_history: chatHistory,
        notes: notes,
        created: new Date().toISOString(),
        timestamp: new Date().toISOString(),
        status: 'in_progress'
      };

      // Save to localStorage as backup
      localStorage.setItem(`session_${sessionData.session_id}`, JSON.stringify(sessionData));
      
      setSessionId(sessionData.session_id);
      setHasSaved(true);
      
      // Show success feedback
      alert('Session saved successfully!');
    } catch (error) {
      console.error('Save error:', error);
      alert('Failed to save session. Please try again.');
    }
  };

  // Get current phase info
  const currentPhaseInfo = documentPhases[currentDocType][currentPhase - 1];
  const progressPercentage = Math.round((currentPhase / 3) * 100);

  return (
    <div className={`wizard-container ${currentDocType}`}>
      {/* Header */}
      <div className="wizard-header">
        <div className="back-to-workspace">
          <button onClick={() => navigate('/dashboard')} className="back-link">
            Back to Workspace
          </button>
        </div>
        
        <div className="header-controls">
          <div className="help-mode-toggle">
            <label className="switch">
              <input 
                type="checkbox" 
                checked={detailedMode}
                onChange={(e) => setDetailedMode(e.target.checked)}
              />
              <span className="slider round"></span>
            </label>
            <span className="toggle-label">
              Detailed: {detailedMode ? 'ON' : 'OFF'}
            </span>
          </div>
          
          <div className="icon-row">
            <button className="collab-icon" title="Collaborate">
              <img src="/collaborate-icon.svg" alt="Collaborate" />
            </button>
            <button className="help-icon" title="Help">?</button>
          </div>
        </div>
      </div>

      {/* Document Type Selector */}
      <div className="document-type-switcher">
        <label htmlFor="documentTypeSelect">Analysis Type:</label>
        <select 
          id="documentTypeSelect"
          value={currentDocType}
          onChange={(e) => handleDocTypeChange(e.target.value)}
        >
          <option value="market_analysis">Market Analysis – Vet a New Product/Service</option>
          <option value="gap_analysis">Gap Analysis – Improve an Existing Product/Service</option>
          <option value="swot_analysis">SWOT Analysis – Assess Strengths, Weaknesses, Opportunities & Threats</option>
        </select>
      </div>

      {/* Phase Navigation */}
      <div className="phase-navigation">
        <button 
          className="nav-button"
          onClick={handlePrevPhase}
          disabled={currentPhase === 1}
        >
          Back
        </button>
        
        <div className="phase-progress-container">
          <div className="phase-title">
            Phase {currentPhase}: {currentPhaseInfo.title}
          </div>
          <div className="progress-container">
            <span className="progress-percentage">{progressPercentage}%</span>
            <div className="progress-bar-container">
              <div 
                className="progress-bar" 
                style={{ width: `${progressPercentage}%` }}
              ></div>
            </div>
          </div>
        </div>
        
        <button 
          className="nav-button"
          onClick={handleNextPhase}
        >
          {currentPhase === 3 ? 'Finish' : 'Next'}
        </button>
      </div>

      {/* Main Content */}
      <div className="wizard-content">
        {/* Chat Column */}
        <div className="wizard-chat-column">
          <div className="chat-container">
            <div className="chat-history" ref={chatHistoryRef}>
              {chatHistory.map((msg, index) => (
                <div key={index} className={`${msg.type}-message`}>
                  {msg.type === 'system' ? (
                    <div dangerouslySetInnerHTML={{ __html: msg.content }} />
                  ) : (
                    <div>{msg.content}</div>
                  )}
                </div>
              ))}
              
              {isLoading && (
                <div className="loading-indicator">
                  <div className="dot-animation">
                    <span></span><span></span><span></span>
                  </div>
                </div>
              )}
            </div>
            
            <div className="chat-input-container">
              <div className="enter-key-option">
                <input 
                  type="checkbox" 
                  id="enterToSend"
                  checked={enterToSend}
                  onChange={(e) => setEnterToSend(e.target.checked)}
                />
                <label htmlFor="enterToSend">Press Enter to send</label>
              </div>
              
              <div className="textarea-submit-wrapper">
                <textarea
                  value={userInput}
                  onChange={(e) => setUserInput(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Type your message here..."
                />
                <button 
                  className="submit-icon-button"
                  onClick={handleSubmit}
                  disabled={isLoading}
                >
                  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="20" height="20">
                    <path fill="var(--primary-color)" d="M498.1 5.6c10.1 7 15.4 19.1 13.5 31.2l-64 416c-1.5 9.7-7.4 18.2-16 23s-18.9 5.4-28 1.6L284 427.7l-68.5 74.1c-8.9 9.7-22.9 12.9-35.2 8.1S160 493.2 160 480l0-83.6c0-4 1.5-7.8 4.2-10.8L331.8 202.8c5.8-6.3 5.6-16-.4-22s-15.7-6.4-22-.7L106 360.8 17.7 316.6C7.1 311.3 .3 300.7 0 288.9s5.9-22.8 16.1-28.7l448-256c10.7-6.1 23.9-5.5 34 1.4z"/>
                  </svg>
                </button>
              </div>
              
              <p className="loading-notice">
                After submitting, please wait while content is generated. Do not refresh the page.
              </p>
            </div>
          </div>
        </div>

        {/* Notes Column */}
        <div className="wizard-notes-column">
          <div className="notes-container">
            <h3>Session Notes</h3>
            
            <div className="notes-tabs">
              {[1, 2, 3].map(phase => (
                <button
                  key={phase}
                  className={`tab-button ${activeNotesTab === `phase${phase}` ? 'active' : ''}`}
                  onClick={() => setActiveNotesTab(`phase${phase}`)}
                >
                  Phase {phase}
                </button>
              ))}
            </div>
            
            <div className="tab-content">
              {[1, 2, 3].map(phase => (
                <div
                  key={phase}
                  className={`tab-pane ${activeNotesTab === `phase${phase}` ? 'active' : ''}`}
                >
                  <textarea
                    value={notes[`phase${phase}`]}
                    onChange={(e) => setNotes(prev => ({
                      ...prev,
                      [`phase${phase}`]: e.target.value
                    }))}
                    placeholder={`Add notes for Phase ${phase} here...`}
                  />
                </div>
              ))}
            </div>
            
            <div className="action-buttons">
              <button className="action-button save-button" onClick={handleSaveSession}>
                Save Session
              </button>
              <button 
                className="action-button review-button"
                onClick={() => navigate('/sessions')}
              >
                Review Progress
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Finish Modal */}
      {showFinishModal && (
        <div className="modal-overlay">
          <div className="finish-modal">
            <h2>Session Complete!</h2>
            <p>Your analysis session has been completed and saved. What would you like to do next?</p>
            
            <div className="finish-modal-buttons">
              <button 
                className="action-button pdf-button"
                onClick={() => {
                  // TODO: Implement PDF generation
                  alert('PDF generation feature coming soon!');
                }}
              >
                View PDF
              </button>
              <button 
                className="action-button sessions-button"
                onClick={() => {
                  setShowFinishModal(false);
                  navigate('/sessions');
                }}
              >
                Manage Sessions
              </button>
            </div>
            
            <button 
              className="modal-close"
              onClick={() => {
                setShowFinishModal(false);
                navigate('/dashboard');
              }}
            >
              Close
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default Wizard;

