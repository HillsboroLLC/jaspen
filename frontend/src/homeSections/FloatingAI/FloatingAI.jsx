import React, { useState, useEffect, useRef } from 'react';
import styles from './FloatingAI.module.css';
import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';

const FloatingAI = ({ 
  isGuidedMode = false, 
  currentPage = 'unknown',
  currentTool = 'unknown',
  onDataUpdate = null,
  formData = {},
  setFormData = null,
  statisticalContext = null  // NEW: Statistical context for Statistics tool
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [inputMessage, setInputMessage] = useState('');
  const [isTyping, setIsTyping] = useState(false);
  const [hasNewMessage, setHasNewMessage] = useState(false);
  const [extractedData, setExtractedData] = useState({});
  const messagesEndRef = useRef(null);

  // Data extraction patterns for different tools
  const dataPatterns = {
    a3: {
      projectTitle: /(?:project title|title|project name)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      problemOwner: /(?:problem owner|owner|responsible)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      teamMembers: /(?:team members?|team|members?)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      background: /(?:background|context|situation)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      problemStatement: /(?:problem statement|problem|issue)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      businessImpact: /(?:business impact|impact|effect)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      currentStateDescription: /(?:current state|current situation|as-is)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      goalStatement: /(?:goal|target|objective)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      targetStateDescription: /(?:target state|future state|to-be)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      results: /(?:results?|outcomes?|achievements?)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      lessonsLearned: /(?:lessons? learned|learnings?|takeaways?)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      nextSteps: /(?:next steps?|future actions?|follow.?up)(?:\s*:?\s*)(.*?)(?:\.|$)/i
    },
    finy: {
      projectTitle: /(?:project title|title|project name)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      baseline: /(?:baseline|current performance|starting point)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      target: /(?:target|goal|improvement target)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      timeframe: /(?:timeframe|timeline|duration)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      cost: /(?:cost|investment|budget)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      savings: /(?:savings|benefit|roi)(?:\s*:?\s*)(.*?)(?:\.|$)/i
    },
    // NEW: Statistical analysis patterns
    statistics: {
      analysisGoal: /(?:goal|objective|want to|analyze|looking for)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      targetVariable: /(?:target|dependent|outcome|response)(?:\s*variable|column)?(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      groupVariable: /(?:group|category|factor|independent)(?:\s*variable|column)?(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      hypothesis: /(?:hypothesis|expect|think|believe)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      significance: /(?:significance|alpha|p.?value)(?:\s*:?\s*)(.*?)(?:\.|$)/i,
      testType: /(?:test|analysis|method)(?:\s*:?\s*)(.*?)(?:\.|$)/i
    }
  };

  // Get context-aware welcome message
  const getWelcomeMessage = (page, tool) => {
    const welcomeMessages = {
      'a3': "Hi! I'm Kii, your A3 Problem Solving assistant. I can help you fill out your A3 form by asking you questions and automatically populating the fields. Let's start with your project title - what problem are you working on?",
      'finy': "Hello! I'm Kii, your FinY assistant. I can help you calculate financial benefits and fill out your analysis. What project are you analyzing for financial impact?",
      'sipoc': "Hi! I'm Kii, here to help you create your SIPOC diagram. I can guide you through each section and fill in the details. What process are you mapping?",
      'statistics': getStatisticalWelcomeMessage(),
      'default': `Hi! I'm Kii, your ${tool} assistant. I can help you fill out the form and guide you through the process. What would you like to work on?`
    };
    return welcomeMessages[tool.toLowerCase()] || welcomeMessages['default'];
  };

  // NEW: Generate statistical analysis welcome message based on context
  const getStatisticalWelcomeMessage = () => {
    if (!statisticalContext) {
      return "Hi! I'm Kii, your Statistical Analysis assistant. Upload a dataset and I'll help you choose the right analysis methods and interpret your results. What would you like to analyze?";
    }

    const { dataset, analysis } = statisticalContext;
    
    if (!dataset.hasData) {
      return "Hi! I'm Kii, your Statistical Analysis assistant. I can help you choose the right statistical methods, interpret results, and guide you through your analysis. Start by uploading a CSV file and I'll analyze your data structure!";
    }

    if (dataset.rowCount > 0) {
      return `Great! I can see you've uploaded "${dataset.fileName}" with ${dataset.rowCount} rows and ${dataset.columnCount} columns. I found ${dataset.numericColumns.length} numeric and ${dataset.categoricalColumns.length} categorical variables. What type of analysis would you like to perform?`;
    }

    return "Hi! I'm Kii, your Statistical Analysis assistant. I'm here to help you with statistical analysis, hypothesis testing, and data interpretation. What can I help you with today?";
  };

  // Initialize with context-aware welcome message
  useEffect(() => {
    if (isGuidedMode && messages.length === 0) {
      const welcomeMessage = getWelcomeMessage(currentPage, currentTool);
      setMessages([{
        id: Date.now(),
        type: 'ai',
        content: welcomeMessage,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      }]);
    }
  }, [currentPage, currentTool, messages.length, isGuidedMode, statisticalContext]);

  // Auto-scroll to bottom of messages
  useEffect(() => {
    if (isGuidedMode) {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isGuidedMode]);

  // Extract data from user messages
  const extractDataFromMessage = (message, tool) => {
    const patterns = dataPatterns[tool.toLowerCase()] || {};
    const extracted = {};

    Object.entries(patterns).forEach(([field, pattern]) => {
      const match = message.match(pattern);
      if (match && match[1]) {
        extracted[field] = match[1].trim();
      }
    });

    return extracted;
  };

  // Update form data based on extracted information
  const updateFormData = (extractedData) => {
    if (setFormData && Object.keys(extractedData).length > 0) {
      setFormData(prev => ({
        ...prev,
        ...extractedData,
        lastUpdated: new Date().toISOString().split('T')[0]
      }));

      // Trigger callback if provided
      if (onDataUpdate) {
        onDataUpdate(extractedData);
      }

      setExtractedData(prev => ({ ...prev, ...extractedData }));
    }
  };

  const requestBackendResponse = async (userInput, mergedFormData) => {
    const payload = {
      message: userInput,
      tool: String(currentTool || 'unknown').toLowerCase(),
      context: {
        page: currentPage || 'unknown',
        formData: mergedFormData || {},
        statisticalContext: statisticalContext || null
      }
    };

    const response = await fetch(`${API_BASE}/api/v1/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, 'POST'),
      body: JSON.stringify(payload)
    });

    const json = await response.json().catch(() => ({}));
    if (!response.ok || !json?.success || typeof json?.response !== 'string') {
      throw new Error(json?.error || `Chat request failed (${response.status})`);
    }
    return json.response.trim();
  };

  // Toggle chat window
  const toggleChat = () => {
    setIsOpen(!isOpen);
    if (!isOpen) {
      setHasNewMessage(false);
    }
  };

  // Handle sending messages
  const handleSendMessage = async () => {
    if (!inputMessage.trim() || isTyping) return;

    const outgoingMessage = inputMessage.trim();
    const extracted = extractDataFromMessage(outgoingMessage, currentTool);
    if (Object.keys(extracted).length > 0) {
      updateFormData(extracted);
    }

    const mergedFormData = { ...(formData || {}), ...(extractedData || {}), ...extracted };

    // Add user message
    const userMessage = {
      id: Date.now(),
      type: 'user',
      content: outgoingMessage,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, userMessage]);
    setInputMessage('');
    setIsTyping(true);

    try {
      const aiResponse = await requestBackendResponse(outgoingMessage, mergedFormData);
      const aiMessage = {
        id: Date.now() + 1,
        type: 'ai',
        content: aiResponse,
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };

      setMessages(prev => [...prev, aiMessage]);
      setIsTyping(false);
      
      if (!isOpen) {
        setHasNewMessage(true);
      }
    } catch (error) {
      const fallbackMessage = {
        id: Date.now() + 1,
        type: 'ai',
        content: "I'm having trouble reaching the AI service right now. Please try again in a moment.",
        timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
      };
      setMessages(prev => [...prev, fallbackMessage]);
      setIsTyping(false);
      if (!isOpen) {
        setHasNewMessage(true);
      }
      console.error('FloatingAI chat request failed:', error);
    }
  };

  // Handle quick actions
  const handleQuickAction = (action) => {
    const quickMessages = {
      help: `What can you help me with in ${currentTool}?`,
      example: `Can you give me an example for ${currentTool}?`,
      start: `How do I get started with ${currentTool}?`,
      correlations: "I want to analyze correlations between variables",
      compare: "I want to compare groups in my data"
    };

    if (quickMessages[action]) {
      setInputMessage(quickMessages[action]);
      setHasNewMessage(false);
    }
  };

  // Handle Enter key
  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  // Don't render if not in guided mode
  if (!isGuidedMode) {
    return null;
  }

  return (
    <div className={styles.floatingAI}>
      {/* Floating Button */}
      <button 
        className={`${styles.floatingBtn} ${isOpen ? styles.open : ''}`}
        onClick={toggleChat}
        aria-label={isOpen ? "Close AI Assistant" : "Open AI Assistant"}
      >
        {hasNewMessage && !isOpen && <div className={styles.notification}></div>}
        <i className={isOpen ? "fas fa-times" : "fas fa-wand-magic-sparkles"}></i>
      </button>

      {/* Chat Window */}
      {isOpen && (
        <div className={styles.chatWindow}>
          {/* Header */}
          <div className={styles.chatHeader}>
            <div className={styles.headerInfo}>
              <div className={styles.aiAvatar}>
                <i className="fas fa-wand-magic-sparkles"></i>
              </div>
              <div className={styles.headerText}>
                <h4>Kii</h4>
                <span className={styles.status}>
                  {isTyping ? 'Typing...' : 'Ready to help'}
                </span>
              </div>
            </div>
            <div className={styles.headerActions}>
              <button 
                className={styles.minimizeBtn}
                onClick={toggleChat}
                aria-label="Minimize chat"
              >
                <i className="fas fa-minus"></i>
              </button>
            </div>
          </div>

          {/* Messages */}
          <div className={styles.messagesContainer} aria-live="polite" aria-relevant="additions text">
            {messages.map((message) => (
              <div 
                key={message.id} 
                className={`${styles.message} ${styles[message.type]}`}
              >
                <div className={styles.messageContent}>
                  {message.content.split('\n').map((line, index) => (
                    <div key={index}>{line}</div>
                  ))}
                </div>
                <div className={styles.messageTime}>
                  {message.timestamp}
                </div>
              </div>
            ))}
            
            {isTyping && (
              <div className={`${styles.message} ${styles.ai}`}>
                <div className={styles.typingIndicator}>
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            )}
            <div ref={messagesEndRef} />
          </div>

          {/* Quick Actions */}
          <div className={styles.quickActions}>
            <button 
              className={styles.quickBtn}
              onClick={() => handleQuickAction('help')}
            >
              <i className="fas fa-question-circle"></i>
              Help
            </button>
            <button 
              className={styles.quickBtn}
              onClick={() => handleQuickAction('example')}
            >
              <i className="fas fa-lightbulb"></i>
              Example
            </button>
            <button 
              className={styles.quickBtn}
              onClick={() => handleQuickAction('start')}
            >
              <i className="fas fa-play"></i>
              Start
            </button>
            {currentTool.toLowerCase() === 'statistics' && (
              <>
                <button 
                  className={styles.quickBtn}
                  onClick={() => handleQuickAction('correlations')}
                >
                  <i className="fas fa-chart-line"></i>
                  Correlations
                </button>
                <button 
                  className={styles.quickBtn}
                  onClick={() => handleQuickAction('compare')}
                >
                  <i className="fas fa-balance-scale"></i>
                  Compare
                </button>
              </>
            )}
          </div>

          {/* Input */}
          <div className={styles.chatInput}>
            <input
              type="text"
              value={inputMessage}
              onChange={(e) => setInputMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={`Ask Kii about ${currentTool}...`}
              className={styles.messageInput}
            />
            <button 
              onClick={handleSendMessage}
              disabled={!inputMessage.trim() || isTyping} aria-disabled={!inputMessage.trim() || isTyping}
              className={styles.sendBtn}
              aria-label="Send message"
            >
              <i className="fas fa-paper-plane"></i>
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

export default FloatingAI;
