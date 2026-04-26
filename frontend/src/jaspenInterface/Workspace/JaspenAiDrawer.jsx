import React, { useRef } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPaperPlane, faTimes } from '@fortawesome/free-solid-svg-icons';
import './JaspenAiDrawer.css';

export default function JaspenAiDrawer({
  isOpen = false,
  onClose,
  onOpen,
  showSideTab = true,
  sideTabTop = 200,
  id = 'jas-ai-drawer-panel',
  panelRef = null,
  messagesContainerRef = null,
  messagesEndRef: externalEndRef,
  messages = [],
  renderMessage,
  renderAttachments,
  renderActions,
  input = '',
  onInputChange,
  onInputKeyDown,
  onSend,
  placeholder = 'Ask Jaspen…',
  busy = false,
  starterPrompts = [],
  streamStatus = null,
  tabs = null,
  activeDrawerTab,
  onDrawerTabChange,
  alternateContent = null,
  extraPanel = null,
  footer = null,
  inputExtras = null,
}) {
  const internalEndRef = useRef(null);
  const endRef = externalEndRef || internalEndRef;

  const defaultRenderMessage = (msg) => {
    const text = msg?.text ?? msg?.content ?? '';
    return <span>{typeof text === 'string' ? text : JSON.stringify(text)}</span>;
  };

  const renderMsg = renderMessage || defaultRenderMessage;
  const showAssistantView = !tabs || !activeDrawerTab || activeDrawerTab === (tabs[0]?.key);

  const handleKeyDown = (event) => {
    if (typeof onInputKeyDown === 'function') {
      onInputKeyDown(event);
      return;
    }
    if (event.key === 'Enter' && !event.shiftKey) {
      event.preventDefault();
      onSend?.();
    }
  };

  return (
    <>
      {showSideTab && !isOpen && (
        <button
          type="button"
          className="jas-sidebar-tab jas-tab-assistant"
          style={{ top: `${sideTabTop}px` }}
          onClick={onOpen}
          aria-label="Jaspen"
          title="Jaspen"
          aria-expanded={false}
          aria-controls={id}
        >
          <span className="jas-tab-label">Jaspen</span>
        </button>
      )}

      <div
        id={id}
        ref={panelRef}
        className={`jas-ai-drawer${isOpen ? ' jas-drawer-open' : ''}`}
        aria-label="Jaspen assistant drawer"
      >
        <div className="jas-ai-header">
          <div className="jas-ai-title"><span>Jaspen</span></div>
          <button className="jas-close-btn" onClick={onClose} aria-label="Close assistant drawer">
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>

        {tabs && tabs.length > 1 && (
          <div className="jas-ai-toggle" role="tablist" aria-label="Assistant drawer views">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                type="button"
                className={`jas-ai-toggle-btn${activeDrawerTab === tab.key ? ' active' : ''}`}
                onClick={() => onDrawerTabChange?.(tab.key)}
                role="tab"
                aria-selected={activeDrawerTab === tab.key}
                tabIndex={activeDrawerTab === tab.key ? 0 : -1}
              >
                {tab.label}
              </button>
            ))}
          </div>
        )}

        {showAssistantView ? (
          <>
            <div className="jas-ai-messages" ref={messagesContainerRef}>
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  className={`jas-ai-message ${msg.role === 'user' ? 'user' : 'assistant'}`}
                >
                  <div className="jas-message-content">{renderMsg(msg)}</div>
                  {renderAttachments?.(msg)}
                  {renderActions?.(msg, `drawer:${idx}`, idx, messages.length)}
                </div>
              ))}
              <div ref={endRef} aria-hidden="true" />
            </div>

            {streamStatus}
            {extraPanel}

            <div className="jas-ai-input-area">
              {starterPrompts.length > 0 && (
                <div className="jas-ai-starter-row">
                  {starterPrompts.map((prompt) => (
                    <button
                      key={prompt}
                      type="button"
                      className="jas-ai-starter-chip"
                      onClick={() => onInputChange?.(prompt)}
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              )}
              {inputExtras}
              <div className="jas-ai-input-row">
                <textarea
                  className="jas-ai-input"
                  placeholder={placeholder}
                  rows={3}
                  value={input}
                  onChange={(event) => onInputChange?.(event.target.value)}
                  onKeyDown={handleKeyDown}
                  disabled={busy}
                />
                <button
                  className="jas-ai-send-btn"
                  onClick={onSend}
                  aria-label="Send assistant message"
                  disabled={busy || !String(input).trim()}
                  aria-disabled={busy || !String(input).trim()}
                >
                  <FontAwesomeIcon icon={faPaperPlane} />
                </button>
              </div>
            </div>
          </>
        ) : (
          <div className="jas-ai-messages">
            {alternateContent}
          </div>
        )}

        {footer}
      </div>
    </>
  );
}
