export const userMessageWhitespaceStyle = {
  whiteSpace: 'pre-wrap',
  overflowWrap: 'anywhere',
  wordBreak: 'break-word',
};

export function streamFailurePresentation(error, creditMessage = null) {
  const payload = error?.data && typeof error.data === 'object' ? error.data : {};
  return {
    message: creditMessage || payload.error || 'Sorry — I hit an error. Please try again.',
    retryable: !creditMessage && payload.retryable !== false,
    threadId: payload.thread_id || payload.session_id || null,
  };
}
