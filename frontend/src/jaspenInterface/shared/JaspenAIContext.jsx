import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
} from 'react';
import { useLocation } from 'react-router-dom';
import { Jaspen } from '../Workspace/JaspenClient';

const JaspenAIContext = createContext(null);

export const useJaspenAI = () => useContext(JaspenAIContext);

const PROJECT_THREAD_PATHS = new Set(['/new', '/execution-plan']);
const COMPRESSION_THRESHOLD = 50;

let _msgCounter = 0;
const genId = () => `jm_${Date.now()}_${_msgCounter++}`;

export function JaspenAIProvider({ children }) {
  const location = useLocation();
  const [messages, setMessages] = useState([]);
  const [threadId, setThreadId] = useState(null);
  const [isBusy, setIsBusy] = useState(false);
  const [isOpen, setIsOpen] = useState(false);
  const [compressionIndex, setCompressionIndex] = useState(null);
  const companionSessionRef = useRef(null);
  const prevPathRef = useRef(location.pathname);

  const mode = PROJECT_THREAD_PATHS.has(location.pathname) ? 'project' : 'standalone';

  const getViewContext = useCallback(() => {
    const p = location.pathname;
    const params = new URLSearchParams(location.search);
    const activeTab = params.get('tab') || undefined;
    if (p === '/new') return { current_view: 'workspace' };
    if (p === '/execution-plan') return { current_view: 'execution' };
    if (p === '/connectors-manage') return { current_view: 'connectors' };
    if (p === '/insights') return { current_view: 'insights' };
    if (p === '/account') return { current_view: 'account', active_tab: activeTab };
    if (p === '/knowledge') return { current_view: 'knowledge' };
    if (p === '/team') return { current_view: 'team' };
    return { current_view: 'general' };
  }, [location.pathname, location.search]);

  // Reset standalone session when leaving standalone mode entirely
  useEffect(() => {
    const wasStandalone = !PROJECT_THREAD_PATHS.has(prevPathRef.current);
    const isNowProject = PROJECT_THREAD_PATHS.has(location.pathname);
    prevPathRef.current = location.pathname;
    if (wasStandalone && isNowProject) {
      companionSessionRef.current = null;
    }
  }, [location.pathname]);

  const appendDelta = useCallback((id, delta) => {
    setMessages(prev =>
      prev.map(m => m.id === id ? { ...m, text: m.text + delta } : m)
    );
  }, []);

  const finalizeMsg = useCallback((id, finalText, error = false) => {
    setMessages(prev =>
      prev.map(m =>
        m.id === id
          ? { ...m, text: finalText !== '' ? finalText : m.text, streaming: false, error }
          : m
      )
    );
  }, []);

  const sendMessage = useCallback(async (text, { files, connectorData, projectThreadId } = {}) => {
    const trimmed = String(text || '').trim();
    if (!trimmed || isBusy) return;

    const userMsgId = genId();
    const asstMsgId = genId();

    setMessages(prev => {
      const next = [
        ...prev,
        { id: userMsgId, role: 'user', text: trimmed },
        { id: asstMsgId, role: 'assistant', text: '', streaming: true },
      ];
      if (next.length >= COMPRESSION_THRESHOLD && compressionIndex === null) {
        setCompressionIndex(Math.floor(next.length / 2));
      }
      return next;
    });
    setIsBusy(true);

    const attachments = Array.isArray(files) && files.length ? files : undefined;
    const view_context = getViewContext();
    const effectiveThreadId = projectThreadId || threadId;

    try {
      const sid = companionSessionRef.current;

      if (effectiveThreadId && mode === 'project') {
        // Project thread mode — use same thread so Jaspen has full context
        await Jaspen.streamConversation({
          session_id: effectiveThreadId,
          user_message: trimmed,
          attachments,
          view_context,
          onDelta: (d) => appendDelta(asstMsgId, d),
          onDone: (p) => finalizeMsg(asstMsgId, p?.reply || p?.message || ''),
        });
      } else if (sid) {
        // Continuing standalone companion session
        await Jaspen.streamConversation({
          session_id: sid,
          user_message: trimmed,
          attachments,
          view_context,
          intake_context: connectorData ? { connector_data: connectorData } : undefined,
          onDelta: (d) => appendDelta(asstMsgId, d),
          onDone: (p) => finalizeMsg(asstMsgId, p?.reply || p?.message || ''),
        });
      } else {
        // First standalone message — start a new companion session
        let newSid = null;
        await Jaspen.streamConversationStart({
          description: trimmed,
          view_context,
          intake_context: connectorData ? { connector_data: connectorData } : undefined,
          onDelta: (d) => appendDelta(asstMsgId, d),
          onDone: (p) => {
            newSid = p?.thread_id || p?.session_id || null;
            finalizeMsg(asstMsgId, p?.reply || p?.message || '');
          },
        });
        if (newSid) companionSessionRef.current = newSid;
      }
    } catch {
      finalizeMsg(asstMsgId, 'Something went wrong. Please try again.', true);
    } finally {
      setIsBusy(false);
    }
  }, [isBusy, mode, threadId, compressionIndex, getViewContext, appendDelta, finalizeMsg]);

  const clearConversation = useCallback(() => {
    setMessages([]);
    setCompressionIndex(null);
    companionSessionRef.current = null;
  }, []);

  const value = {
    messages,
    setMessages,
    threadId,
    setThreadId,
    mode,
    isBusy,
    isOpen,
    setIsOpen,
    compressionIndex,
    sendMessage,
    clearConversation,
    currentPath: location.pathname,
  };

  return (
    <JaspenAIContext.Provider value={value}>
      {children}
    </JaspenAIContext.Provider>
  );
}
