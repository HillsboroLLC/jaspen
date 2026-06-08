import React, { useEffect, useRef } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faPaperPlane } from '@fortawesome/free-solid-svg-icons';

export default function WorkspaceAssistantShell({
  isOpen = false,
  onOpen,
  onClose,
  showSideTab = true,
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
  placeholder = 'Describe a change...',
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
  contextLabel = 'Workspace · Beta',
  contextTitle = 'Jaspen',
  contextDescription = null,
  emptyText = null,
}) {
  const internalEndRef = useRef(null);
  const endRef = externalEndRef || internalEndRef;
  const showAssistantView = !tabs || !activeDrawerTab || activeDrawerTab === (tabs[0]?.key);

  useEffect(() => {
    if (!isOpen) return;
    const frame = window.requestAnimationFrame(() => {
      endRef.current?.scrollIntoView({ block: 'end' });
    });
    return () => window.cancelAnimationFrame(frame);
  }, [isOpen, messages.length, busy, endRef]);

  const defaultRenderMessage = (msg) => {
    const text = msg?.text ?? msg?.content ?? '';
    return <span>{typeof text === 'string' ? text : JSON.stringify(text)}</span>;
  };
  const renderMsg = renderMessage || defaultRenderMessage;

  const handleCloseToggle = () => {
    if (isOpen) {
      onClose?.();
    } else {
      onOpen?.();
    }
  };

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

  const handleInputChange = (event) => {
    onInputChange?.(event.target.value);
  };

  const handlePromptClick = (prompt) => {
    const isObject = prompt && typeof prompt === 'object';
    const label = isObject ? String(prompt.label || '').trim() : String(prompt || '').trim();
    if (!label) return;
    if (isObject && prompt.loading) return;
    if (isObject && typeof prompt.onClick === 'function') {
      prompt.onClick();
      return;
    }
    onInputChange?.(label);
  };

  return (
    <>
      <aside
        id={id}
        ref={panelRef}
        data-ws-sidebar
        className="workspace-assistant-shell"
        aria-label="Jaspen assistant drawer"
        style={{
          width: isOpen ? 340 : 0,
          flexShrink: 0,
          background: '#fff',
          borderRight: isOpen ? '1px solid #e6eaf2' : 'none',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'width 0.25s ease',
          position: 'fixed',
          top: 0,
          left: 'var(--workspace-assistant-left, 0px)',
          height: '100vh',
          zIndex: 200,
          boxShadow: 'none',
          fontFamily: 'Inter Tight, system-ui, sans-serif',
        }}
      >
        <div style={{ padding: '14px 16px', borderBottom: '1px solid #e6eaf2' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, alignItems: 'flex-start' }}>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 12, color: '#64748b', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
                {contextLabel}
              </div>
              <div style={{ fontSize: 14, color: '#0f172a', marginTop: 4, fontWeight: 600, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {contextTitle}
              </div>
            </div>
          </div>
          {contextDescription && (
            <div style={{ fontSize: 12, color: '#64748b', marginTop: 2, lineHeight: 1.45 }}>
              {contextDescription}
            </div>
          )}
        </div>

        {tabs && tabs.length > 1 && (
          <div style={{ display: 'flex', gap: 4, padding: '8px 12px', background: '#fff', borderBottom: '1px solid #e6eaf2' }} role="tablist" aria-label="Assistant drawer views">
            {tabs.map((tab) => {
              const active = activeDrawerTab === tab.key;
              return (
                <button
                  key={tab.key}
                  type="button"
                  onClick={() => onDrawerTabChange?.(tab.key)}
                  role="tab"
                  aria-selected={active}
                  tabIndex={active ? 0 : -1}
                  style={{
                    padding: '6px 12px',
                    fontSize: 12,
                    fontWeight: 500,
                    color: active ? '#fff' : '#64748b',
                    background: active ? '#0f172a' : 'transparent',
                    border: active ? '1px solid #0f172a' : '1px solid transparent',
                    borderRadius: 6,
                    cursor: 'pointer',
                    fontFamily: 'inherit',
                  }}
                >
                  {tab.label}
                </button>
              );
            })}
          </div>
        )}

        {showAssistantView ? (
          <>
            <div
              ref={messagesContainerRef}
              style={{ flex: 1, overflow: 'auto', padding: '12px 16px', display: 'flex', flexDirection: 'column', gap: 10 }}
            >
              {messages.length === 0 && (
                <div style={{ fontSize: 12, color: '#94a3b8', lineHeight: 1.5 }}>
                  {emptyText || contextDescription || 'Ask Jaspen for help with this page.'}
                </div>
              )}
              {messages.map((msg, idx) => (
                <div
                  key={idx}
                  style={{
                    alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start',
                    maxWidth: '90%',
                    padding: '8px 12px',
                    borderRadius: 10,
                    background: msg.role === 'user' ? '#0f172a' : '#f1f5f9',
                    color: msg.role === 'user' ? '#fff' : '#0f172a',
                    fontSize: 13,
                    lineHeight: 1.5,
                  }}
                >
                  <div>{renderMsg(msg)}</div>
                  {renderAttachments?.(msg)}
                  {renderActions?.(msg, `drawer:${idx}`, idx, messages.length)}
                </div>
              ))}
              <div ref={endRef} aria-hidden="true" />
            </div>

            {streamStatus}
            {extraPanel}

            <div style={{ padding: '10px 12px 14px', borderTop: '1px solid #e6eaf2' }}>
              {starterPrompts.length > 0 && (
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 10 }}>
                  {starterPrompts.map((prompt) => {
                    const isObject = prompt && typeof prompt === 'object';
                    const label = isObject ? String(prompt.label || '').trim() : String(prompt || '').trim();
                    const key = isObject ? String(prompt.id || label || Math.random()) : label;
                    if (!label) return null;
                    return (
                      <button
                        key={key}
                        type="button"
                        onClick={() => handlePromptClick(prompt)}
                        disabled={Boolean(isObject && prompt.loading)}
                        aria-disabled={Boolean(isObject && prompt.loading)}
                        style={{
                          border: '1px solid #dee2e6',
                          background: '#f8f9fa',
                          color: '#161f3b',
                          borderRadius: 999,
                          padding: '6px 12px',
                          font: 'inherit',
                          fontSize: 12,
                          lineHeight: 1.3,
                          cursor: isObject && prompt.loading ? 'not-allowed' : 'pointer',
                        }}
                      >
                        {isObject && prompt.loading ? 'Loading…' : label}
                      </button>
                    );
                  })}
                </div>
              )}
              {inputExtras}
              <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, background: '#f7f8fa', borderRadius: 10, padding: '8px 10px' }}>
                <textarea
                  rows={1}
                  value={input}
                  onChange={handleInputChange}
                  onKeyDown={handleKeyDown}
                  placeholder={busy ? 'Jaspen is replying…' : placeholder}
                  disabled={busy}
                  style={{
                    flex: 1,
                    border: 'none',
                    outline: 'none',
                    background: 'transparent',
                    fontSize: 13,
                    color: '#0f172a',
                    resize: 'none',
                    maxHeight: 140,
                    overflowY: 'auto',
                    lineHeight: 1.45,
                    fontFamily: 'inherit',
                    padding: 0,
                  }}
                />
                <button
                  type="button"
                  onClick={onSend}
                  disabled={busy || !String(input).trim()}
                  aria-label="Send"
                  aria-disabled={busy || !String(input).trim()}
                  style={{
                    width: 30,
                    height: 30,
                    borderRadius: 8,
                    border: 'none',
                    background: String(input).trim() && !busy ? '#0f172a' : '#cbd5e1',
                    color: '#fff',
                    cursor: String(input).trim() && !busy ? 'pointer' : 'not-allowed',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                  }}
                >
                  <FontAwesomeIcon icon={faPaperPlane} style={{ fontSize: 11 }} />
                </button>
              </div>
            </div>
          </>
        ) : (
          <div style={{ flex: 1, overflow: 'auto', padding: '12px 16px' }}>
            {alternateContent}
          </div>
        )}

        {footer}
      </aside>

      {showSideTab && (
        <button
          data-ws-sidebar
          className="workspace-assistant-toggle"
          type="button"
          onClick={handleCloseToggle}
          title={isOpen ? 'Collapse chat' : 'Expand chat'}
          aria-label={isOpen ? 'Collapse chat panel' : 'Expand chat panel'}
          aria-expanded={isOpen}
          aria-controls={id}
          style={{
            position: 'fixed',
            left: isOpen
              ? 'calc(var(--workspace-assistant-left, 0px) + 332px)'
              : 'var(--workspace-assistant-left, 0px)',
            top: '50%',
            transform: 'translateY(-50%)',
            zIndex: 210,
            width: 20,
            height: 48,
            borderRadius: '0 6px 6px 0',
            borderWidth: '1px 1px 1px 0',
            borderStyle: 'solid',
            borderColor: '#e6eaf2',
            background: '#fff',
            color: '#64748b',
            cursor: 'pointer',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 10,
            transition: 'left 0.25s ease',
            padding: 0,
          }}
        >
          {isOpen ? '‹' : '›'}
        </button>
      )}
    </>
  );
}
