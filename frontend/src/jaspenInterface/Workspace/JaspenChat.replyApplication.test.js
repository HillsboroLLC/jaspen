const fs = require('fs');
const path = require('path');

const chat = fs.readFileSync(path.join(__dirname, 'JaspenChat.jsx'), 'utf8');

test('a reply payload adds its artifacts once, including artifacts without an id', () => {
  expect(chat).toContain('appliedArtifactPayloadsRef.current.has(payload)');
  expect(chat).toContain('Artifacts without an id (a trade-off) match on their content.');
});

test('"Thinking…" ends when the reply arrives, not after the background refresh', () => {
  const body = chat.slice(chat.indexOf('async function continueConversation'), chat.indexOf('// Re-send the last user message'));
  expect(body.indexOf('setBusy(false);')).toBeLessThan(body.indexOf('await applyMutationRefreshes(data, sessionId);'));
  expect(body).toContain('void (async () => {');
});
