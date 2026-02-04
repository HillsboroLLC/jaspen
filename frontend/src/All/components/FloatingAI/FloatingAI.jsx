import React, { useState, useEffect, useRef } from 'react';
import styles from './FloatingAI.module.css';

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

  // NEW: Generate statistical analysis response
  const generateStatisticalResponse = (userInput) => {
    if (!statisticalContext) {
      return "I'd love to help with your statistical analysis! Please upload a dataset first so I can provide specific guidance based on your data.";
    }

    const { dataset, analysis, recommendations } = statisticalContext;
    const input = userInput.toLowerCase();

    // Handle specific statistical questions
    if (input.includes('correlation') || input.includes('relationship')) {
      if (dataset.numericColumns.length >= 2) {
        return `Perfect! I can see you have ${dataset.numericColumns.length} numeric columns: ${dataset.numericColumns.join(', ')}. For correlation analysis, I recommend running the "Association / Relationships" analysis. This will compute Pearson correlations between all numeric pairs. Would you like me to guide you through setting this up?`;
      } else {
        return `For correlation analysis, you need at least 2 numeric variables. I can see you have ${dataset.numericColumns.length} numeric columns. Consider if any categorical variables could be converted to numeric, or upload additional data.`;
      }
    }

    if (input.includes('compare') || input.includes('group') || input.includes('difference')) {
      if (dataset.numericColumns.length >= 1 && dataset.categoricalColumns.length >= 1) {
        return `Great! For group comparisons, I can see you have numeric variables (${dataset.numericColumns.join(', ')}) and categorical variables (${dataset.categoricalColumns.join(', ')}). Set your analysis goal to "Compare Groups", then select a numeric target variable and a categorical grouping variable. This will perform t-tests or ANOVA depending on the number of groups.`;
      } else {
        return `For group comparisons, you need at least one numeric variable (for the outcome) and one categorical variable (for the groups). Currently you have ${dataset.numericColumns.length} numeric and ${dataset.categoricalColumns.length} categorical variables.`;
      }
    }

    if (input.includes('describe') || input.includes('summary') || input.includes('overview')) {
      return `Perfect! For descriptive statistics, set your goal to "Describe / Summarize". This will give you summary statistics for numeric variables (mean, SD, min, max) and frequency tables for categorical variables. With ${dataset.rowCount} rows, you'll get reliable statistics.`;
    }

    if (input.includes('predict') || input.includes('model') || input.includes('regression')) {
      return `For predictive modeling, set your goal to "Predictive (beta)". This is still in development, but it will help you build baseline models. Make sure you have a clear target variable you want to predict.`;
    }

    if (input.includes('help') || input.includes('what') || input.includes('how')) {
      return getStatisticalHelpResponse();
    }

    if (input.includes('recommend') || input.includes('suggest') || input.includes('should')) {
      return getStatisticalRecommendations();
    }

    // Default response with context
    if (dataset.hasData) {
      return `I can help you analyze your dataset "${dataset.fileName}". Based on your ${dataset.numericColumns.length} numeric and ${dataset.categoricalColumns.length} categorical variables, I recommend: ${recommendations.slice(0, 2).join(', ')}. What specific question are you trying to answer with your data?`;
    }

    return "I'm here to help with your statistical analysis! Upload a dataset and tell me what you're trying to discover or prove with your data.";
  };

  // NEW: Get statistical help response
  const getStatisticalHelpResponse = () => {
    if (!statisticalContext?.dataset.hasData) {
      return "I can help you with statistical analysis! Here's what I can do:\n\n• Guide you through choosing the right statistical tests\n• Interpret your results and explain what they mean\n• Recommend analysis methods based on your data types\n• Help with hypothesis testing and significance\n\nStart by uploading a CSV file and I'll analyze your data structure!";
    }

    const { dataset } = statisticalContext;
    return `I can help you analyze your dataset with ${dataset.rowCount} rows and ${dataset.columnCount} columns:\n\n• **Descriptive Analysis**: Summary statistics and distributions\n• **Correlation Analysis**: Relationships between variables (${dataset.numericColumns.length} numeric variables available)\n• **Group Comparisons**: Compare means across categories (${dataset.categoricalColumns.length} categorical variables available)\n• **Hypothesis Testing**: Test your research questions\n\nWhat type of analysis interests you most?`;
  };

  // NEW: Get statistical recommendations
  const getStatisticalRecommendations = () => {
    if (!statisticalContext?.dataset.hasData) {
      return "Upload your dataset first and I'll provide specific recommendations based on your data structure and research questions!";
    }

    const { dataset, recommendations } = statisticalContext;
    
    let response = `Based on your data structure, here are my recommendations:\n\n`;
    
    if (dataset.numericColumns.length >= 2) {
      response += `• **Correlation Analysis**: You have ${dataset.numericColumns.length} numeric variables - perfect for exploring relationships\n`;
    }
    
    if (dataset.numericColumns.length >= 1 && dataset.categoricalColumns.length >= 1) {
      response += `• **Group Comparisons**: Compare ${dataset.numericColumns[0]} across ${dataset.categoricalColumns[0]} groups\n`;
    }
    
    response += `• **Descriptive Statistics**: Always start here to understand your data\n`;
    
    if (dataset.rowCount > 100) {
      response += `\nWith ${dataset.rowCount} rows, you have good statistical power for most analyses!`;
    }
    
    return response;
  };

  // Generate intelligent follow-up questions
  const generateFollowUpQuestion = (tool, extractedData, allFormData) => {
    if (tool === 'statistics') {
      return generateStatisticalFollowUp();
    }

    const questions = {
      a3: [
        { field: 'projectTitle', question: "Great! Now, who is the problem owner or person responsible for this issue?" },
        { field: 'problemOwner', question: "Perfect! Who are the team members involved in solving this problem?" },
        { field: 'teamMembers', question: "Excellent! Can you provide some background context about why this problem is important to solve now?" },
        { field: 'background', question: "Thanks! Now, can you clearly state the problem without including any solutions?" },
        { field: 'problemStatement', question: "Good! What's the business impact of this problem?" },
        { field: 'businessImpact', question: "Now let's analyze the current state. Can you describe the current situation with facts and data?" },
        { field: 'currentStateDescription', question: "What's your goal or target state for this problem?" },
        { field: 'goalStatement', question: "Can you describe what the target state will look like in detail?" },
        { field: 'targetStateDescription', question: "What results have you achieved so far?" },
        { field: 'results', question: "What lessons have you learned during this process?" },
        { field: 'lessonsLearned', question: "Finally, what are the next steps or future actions?" }
      ],
      finy: [
        { field: 'projectTitle', question: "Great! What's your current baseline performance or starting point?" },
        { field: 'baseline', question: "Perfect! What's your target improvement or goal?" },
        { field: 'target', question: "Excellent! What's the timeframe for this improvement?" },
        { field: 'timeframe', question: "What's the estimated cost or investment required?" },
        { field: 'cost', question: "What savings or benefits do you expect to achieve?" }
      ]
    };

    const toolQuestions = questions[tool.toLowerCase()] || [];
    
    // Find the next unanswered field
    for (const { field, question } of toolQuestions) {
      if (!allFormData[field] || allFormData[field].trim() === '') {
        return question;
      }
    }

    return "Great! You've provided comprehensive information. Is there anything else you'd like to add or modify?";
  };

  // NEW: Generate statistical follow-up questions
  const generateStatisticalFollowUp = () => {
    if (!statisticalContext?.dataset.hasData) {
      return "Upload a dataset and I'll help you choose the right analysis approach!";
    }

    const { dataset, analysis } = statisticalContext;

    if (!analysis.goal || analysis.goal === 'describe') {
      return "What's your main research question? Are you looking to describe your data, compare groups, find relationships, or build predictive models?";
    }

    if (analysis.goal === 'compare' && !analysis.targetCol) {
      return `For group comparisons, which numeric variable would you like to analyze? Your options are: ${dataset.numericColumns.join(', ')}`;
    }

    if (analysis.goal === 'compare' && analysis.targetCol && !analysis.groupCol) {
      return `Great! Now which categorical variable should I use to create the groups? Your options are: ${dataset.categoricalColumns.join(', ')}`;
    }

    return "What specific aspect of your analysis would you like help with? I can explain results, suggest next steps, or help with interpretation.";
  };

  // Generate AI response with data extraction and context awareness
  const generateAIResponse = (userInput, tool) => {
    // Handle statistics tool specially
    if (tool.toLowerCase() === 'statistics') {
      return generateStatisticalResponse(userInput);
    }

    // Extract data from user input
    const extracted = extractDataFromMessage(userInput, tool);
    
    // Update form data if extraction found anything
    if (Object.keys(extracted).length > 0) {
      updateFormData(extracted);
    }

    // Generate contextual responses based on tool
    const responses = {
      a3: [
        "That's a great start! I've captured that information.",
        "Perfect! I can see this is an important problem to solve.",
        "Excellent! That gives me good context about the situation.",
        "Thanks for that detail. It helps me understand the scope better.",
        "Good! That's exactly the kind of information we need for the A3."
      ],
      finy: [
        "Great! I've noted that information for your financial analysis.",
        "Perfect! That will help us calculate the ROI accurately.",
        "Excellent! Those numbers will be important for the business case.",
        "Thanks! I can use that to build your financial projections.",
        "Good data! That helps quantify the business impact."
      ],
      sipoc: [
        "Perfect! I've captured that for your SIPOC diagram.",
        "Great! That helps define the process boundaries clearly.",
        "Excellent! Those details will make your SIPOC more comprehensive.",
        "Thanks! I can use that to complete the process mapping.",
        "Good input! That adds important context to your SIPOC."
      ],
      default: [
        "Thanks for that information! I've captured it.",
        "Great! That helps me understand what you're working on.",
        "Perfect! I can use that to assist you better.",
        "Excellent! That gives me good context.",
        "Good! I've noted that for your project."
      ]
    };

    const toolResponses = responses[tool.toLowerCase()] || responses.default;
    const randomResponse = toolResponses[Math.floor(Math.random() * toolResponses.length)];

    // Generate follow-up question
    const followUp = generateFollowUpQuestion(tool, extracted, { ...formData, ...extractedData });

    return `${randomResponse}\n\n${followUp}`;
  };

  // Toggle chat window
  const toggleChat = () => {
    setIsOpen(!isOpen);
    if (!isOpen) {
      setHasNewMessage(false);
    }
  };

  // Handle sending messages
  const handleSendMessage = () => {
    if (!inputMessage.trim() || isTyping) return;

    // Add user message
    const userMessage = {
      id: Date.now(),
      type: 'user',
      content: inputMessage,
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    };

    setMessages(prev => [...prev, userMessage]);
    setInputMessage('');
    setIsTyping(true);

    // Simulate AI response delay
    setTimeout(() => {
      const aiResponse = generateAIResponse(inputMessage, currentTool);
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
    }, 1000 + Math.random() * 2000); // Random delay between 1-3 seconds
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
          <div className={styles.messagesContainer}>
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
              disabled={!inputMessage.trim() || isTyping}
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
