import React, { useRef, useEffect, useState, useCallback } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faPaperPlane,
  faTimes,
  faPaperclip,
  faDatabase,
  faChevronDown,
  faChevronUp,
  faRobot,
} from '@fortawesome/free-solid-svg-icons';
import { useJaspenAI } from './JaspenAIContext';
import './PersistentAiSidebar.css';

function MessageBubble({ msg }) {
  const text = msg?.text ?? '';
  const isUser = msg.role === 'user';
  const isError = msg.error;
  const isStreaming = msg.streaming;

  return (
    <div className={`jai-msg ${isUser ? 'jai-msg--user' : 'jai-msg--assistant'}${isError ? ' jai-msg--error' : ''}`}>
      <div className="jai-msg-bubble">
        {text ? (
          <span className="jai-msg-text">{text}</span>
        ) : isStreaming ? (
          <span className="jai-msg-typing">
            <span /><span /><span />
          </span>
        ) : null}
      </div>
    </div>
  );
}

function CompressionDivider({ onExpand, count }) {
  return (
    <button
      type="button"
      className="jai-compression-divider"
      onClick={onExpand}
    >
      <FontAwesomeIcon icon={faChevronUp} />
      <span>{count} earlier messages</span>
      <FontAwesomeIcon icon={faChevronDown} />
    </button>
  );
}

export default function PersistentAiSidebar() {
  const {
    messages,
    isBusy,
    isOpen,
    setIsOpen,
    compressionIndex,
    sendMessage,
    mode,
  } = useJaspenAI();

  const [input, setInput] = useState('');
  const [expanded, setExpanded] = useState(false);
  const [attachedFiles, setAttachedFiles] = useState([]);
  const fileInputRef = useRef(null);
  const endRef = useRef(null);
  const textareaRef = useRef(null);

  const visibleMessages = !expanded && compressionIndex !== null
    ? messages.slice(compressionIndex)
    : messages;

  const hiddenCount = compressionIndex !== null ? compressionIndex : 0;

  // Scroll to bottom whenever messages update
  useEffect(() => {
    if (isOpen && endRef.current) {
      endRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isOpen]);

  const handleSend = useCallback(async () => {
    const trimmed = input.trim();
    if (!trimmed || isBusy) return;
    setInput('');
    setAttachedFiles([]);
    await sendMessage(trimmed, { files: attachedFiles.length ? attachedFiles : undefined });
  }, [input, isBusy, sendMessage, attachedFiles]);

  const handleKeyDown = useCallback((e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }, [handleSend]);

  const handleFileChange = useCallback((e) => {
    const files = Array.from(e.target.files || []);
    if (files.length) setAttachedFiles(prev => [...prev, ...files]);
    e.target.value = '';
  }, []);

  const removeFile = useCallback((idx) => {
    setAttachedFiles(prev => prev.filter((_, i) => i !== idx));
  }, []);

  const modeLabel = mode === 'project' ? 'Project Thread' : 'Standalone';

  return (
    <>
      {/* Collapsed tab button */}
      {!isOpen && (
        <button
          type="button"
          className="jai-tab-btn"
          onClick={() => setIsOpen(true)}
          aria-label="Open Jaspen companion"
          title="Jaspen"
        >
          <FontAwesomeIcon icon={faRobot} className="jai-tab-icon" />
          <span className="jai-tab-label">Jaspen</span>
        </button>
      )}

      {/* Sidebar panel */}
      <div
        className={`jai-sidebar${isOpen ? ' jai-sidebar--open' : ''}`}
        aria-label="Jaspen AI companion"
        role="complementary"
      >
        {/* Header */}
        <div className="jai-header">
          <div className="jai-header-left">
            <FontAwesomeIcon icon={faRobot} className="jai-header-icon" />
            <div>
              <div className="jai-header-title">Jaspen</div>
              <div className="jai-header-mode">{modeLabel}</div>
            </div>
          </div>
          <button
            className="jai-close-btn"
            onClick={() => setIsOpen(false)}
            aria-label="Close Jaspen companion"
          >
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {/* Messages */}
        <div className="jai-messages">
          {messages.length === 0 && (
            <div className="jai-empty-state">
              <FontAwesomeIcon icon={faRobot} className="jai-empty-icon" />
              <p>I'm Jaspen, your AI companion.</p>
              <p>Ask me anything — I'll carry this conversation with you across the entire platform.</p>
            </div>
          )}

          {compressionIndex !== null && !expanded && hiddenCount > 0 && (
            <CompressionDivider
              count={hiddenCount}
              onExpand={() => setExpanded(true)}
            />
          )}

          {visibleMessages.map((msg) => (
            <MessageBubble key={msg.id} msg={msg} />
          ))}

          <div ref={endRef} aria-hidden="true" />
        </div>

        {/* Input area */}
        <div className="jai-input-area">
          {attachedFiles.length > 0 && (
            <div className="jai-attachments">
              {attachedFiles.map((f, i) => (
                <div key={i} className="jai-attachment-chip">
                  <span className="jai-attachment-name">{f.name}</span>
                  <button
                    type="button"
                    className="jai-attachment-remove"
                    onClick={() => removeFile(i)}
                    aria-label={`Remove ${f.name}`}
                  >
                    <FontAwesomeIcon icon={faTimes} />
                  </button>
                </div>
              ))}
            </div>
          )}

          <div className="jai-input-row">
            <textarea
              ref={textareaRef}
              className="jai-textarea"
              placeholder="Ask Jaspen…"
              rows={2}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              disabled={isBusy}
            />
            <div className="jai-input-actions">
              <button
                type="button"
                className="jai-icon-btn"
                onClick={() => fileInputRef.current?.click()}
                aria-label="Attach file"
                title="Attach file"
                disabled={isBusy}
              >
                <FontAwesomeIcon icon={faPaperclip} />
              </button>
              <button
                type="button"
                className="jai-icon-btn jai-icon-btn--connector"
                aria-label="Pull from connector"
                title="Pull from connector (coming soon)"
                disabled
              >
                <FontAwesomeIcon icon={faDatabase} />
              </button>
              <button
                className="jai-send-btn"
                onClick={handleSend}
                aria-label="Send"
                disabled={isBusy || !input.trim()}
              >
                <FontAwesomeIcon icon={faPaperPlane} />
              </button>
            </div>
          </div>
        </div>

        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          accept=".pdf,.doc,.docx,.xls,.xlsx,.csv,.txt"
          style={{ display: 'none' }}
          onChange={handleFileChange}
        />
      </div>
    </>
  );
}
