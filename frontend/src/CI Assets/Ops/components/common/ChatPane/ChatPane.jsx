import React, { useState, useEffect } from 'react';
import styles from './ChatPane.module.css';

const ChatPane = ({ 
  toolConfig, 
  currentData = {}, 
  onDataUpdate = () => {},
  className = '' 
}) => {
  const [chatMessages, setChatMessages] = useState([]);
  const [currentMessage, setCurrentMessage] = useState('');
  const [isAITyping, setIsAITyping] = useState(false);

  // Initialize chat with tool-specific welcome message
  useEffect(() => {
    if (toolConfig?.welcomeMessage) {
      setChatMessages([{
        id: 1,
        type: 'ai',
        content: toolConfig.welcomeMessage,
        timestamp: new Date()
      }]);
    }
  }, [toolConfig]);

  // Generate AI response based on tool configuration
  const generateAIResponse = (userMessage) => {
    const lowerMessage = userMessage.toLowerCase();
    
    // Check for tool-specific responses first
    if (toolConfig?.responses) {
      for (const [keyword, response] of Object.entries(toolConfig.responses)) {
        if (lowerMessage.includes(keyword.toLowerCase())) {
          return response;
        }
      }
    }

    // Check for contextual responses based on current data
    if (toolConfig?.contextualResponses && typeof toolConfig.contextualResponses === 'function') {
      const contextualResponse = toolConfig.contextualResponses(userMessage, currentData);
      if (contextualResponse) {
        return contextualResponse;
      }
    }

    // Fallback to default response
    return toolConfig?.defaultResponse || "I can help you with this tool. What would you like to know?";
  };

  // Handle sending chat messages
  const handleSendMessage = async () => {
    if (!currentMessage.trim()) return;

    const userMessage = {
      id: Date.now(),
      type: 'user',
      content: currentMessage,
      timestamp: new Date()
    };

    setChatMessages(prev => [...prev, userMessage]);
    setCurrentMessage('');
    setIsAITyping(true);

    // Simulate AI response delay
    setTimeout(() => {
      const aiResponse = {
        id: Date.now() + 1,
        type: 'ai',
        content: generateAIResponse(currentMessage),
        timestamp: new Date()
      };
      setChatMessages(prev => [...prev, aiResponse]);
      setIsAITyping(false);
    }, 1500);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSendMessage();
    }
  };

  return (
    <div className={`${styles.chatSection} ${className}`}>
      <div className={styles.chatCard}>
        <div className={styles.chatHeader}>
          <h3>
            <i className="fas fa-robot"></i>
            {toolConfig?.title || 'AI Assistant'}
          </h3>
          <div className={styles.chatStatus}>
            {isAITyping ? (
              <span className={styles.typing}>
                <i className="fas fa-circle"></i>
                <i className="fas fa-circle"></i>
                <i className="fas fa-circle"></i>
              </span>
            ) : (
              <span className={styles.online}>Online</span>
            )}
          </div>
        </div>

        <div className={styles.chatMessages}>
          {chatMessages.map((message) => (
            <div
              key={message.id}
              className={`${styles.message} ${styles[message.type]}`}
            >
              <div className={styles.messageContent}>
                {message.content}
              </div>
              <div className={styles.messageTime}>
                {message.timestamp.toLocaleTimeString([], { 
                  hour: '2-digit', 
                  minute: '2-digit' 
                })}
              </div>
            </div>
          ))}
          {isAITyping && (
            <div className={`${styles.message} ${styles.ai}`}>
              <div className={styles.messageContent}>
                <div className={styles.typingIndicator}>
                  <span></span>
                  <span></span>
                  <span></span>
                </div>
              </div>
            </div>
          )}
        </div>

        <div className={styles.chatInput}>
          <div className={styles.inputContainer}>
            <textarea
              value={currentMessage}
              onChange={(e) => setCurrentMessage(e.target.value)}
              onKeyPress={handleKeyPress}
              placeholder={toolConfig?.inputPlaceholder || "Ask me anything about this tool..."}
              className={styles.messageInput}
              rows={1}
            />
            <button
              onClick={handleSendMessage}
              disabled={!currentMessage.trim() || isAITyping}
              className={styles.sendButton}
            >
              <i className="fas fa-paper-plane"></i>
            </button>
          </div>
        </div>

        {/* Quick action buttons if configured */}
        {toolConfig?.quickActions && (
          <div className={styles.quickActions}>
            {toolConfig.quickActions.map((action, index) => (
              <button
                key={index}
                onClick={() => setCurrentMessage(action.message)}
                className={styles.quickActionBtn}
              >
                {action.label}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ChatPane;

