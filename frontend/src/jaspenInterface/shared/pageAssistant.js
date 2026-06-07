import { Jaspen } from '../Workspace/JaspenClient';

export async function sendPageAssistantMessage({
  text,
  messages,
  setMessages,
  sessionId,
  setSessionId,
  setBusy,
  viewContext,
}) {
  const trimmed = String(text || '').trim();
  if (!trimmed) return;

  const assistantIndex = Array.isArray(messages) ? messages.length + 1 : 1;
  setMessages((prev) => [
    ...prev,
    { role: 'user', text: trimmed },
    { role: 'assistant', text: '', streaming: true },
  ]);
  setBusy?.(true);

  let replyText = '';
  const streamArgs = {
    view_context: viewContext,
    onDelta: (delta) => {
      replyText += delta || '';
      setMessages((prev) => prev.map((msg, idx) => (
        idx === assistantIndex ? { ...msg, text: replyText, streaming: true } : msg
      )));
    },
    onDone: (payload) => {
      const finalText = payload?.reply || payload?.message || replyText;
      setMessages((prev) => prev.map((msg, idx) => (
        idx === assistantIndex ? { ...msg, text: finalText, streaming: false } : msg
      )));
    },
  };

  try {
    if (sessionId) {
      await Jaspen.streamConversation({
        ...streamArgs,
        session_id: sessionId,
        user_message: trimmed,
      });
      return;
    }

    let nextSessionId = null;
    await Jaspen.streamConversationStart({
      ...streamArgs,
      description: trimmed,
      onDone: (payload) => {
        nextSessionId = payload?.thread_id || payload?.session_id || null;
        streamArgs.onDone(payload);
      },
    });
    if (nextSessionId) setSessionId?.(nextSessionId);
  } catch (error) {
    setMessages((prev) => prev.map((msg, idx) => (
      idx === assistantIndex
        ? {
          ...msg,
          text: error?.message || 'Something went wrong. Please try again.',
          streaming: false,
          error: true,
        }
        : msg
    )));
  } finally {
    setBusy?.(false);
  }
}
