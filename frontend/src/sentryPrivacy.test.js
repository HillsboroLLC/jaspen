import {
  REDACTED,
  redactSentryText,
  scrubSentryBreadcrumb,
  scrubSentryEvent,
} from './sentryPrivacy';

const providerKey = () => `sk${'_live_'}${'A'.repeat(24)}`;

test('redacts share tokens and credential patterns from URLs and text', () => {
  const key = providerKey();
  const shareToken = 'private-share-token';
  const result = redactSentryText(`https://jaspen.ai/s/${shareToken}?key=${key}`);
  expect(result).not.toContain(shareToken);
  expect(result).not.toContain(key);
  expect(result).toContain(REDACTED);
});

test('event scrubber drops bodies, private headers, content, and user identity', () => {
  const key = providerKey();
  const event = {
    request: {
      method: 'POST',
      url: 'https://api.jaspen.ai/api/v1/shares/manage/private-token',
      headers: { Authorization: `Bearer ${key}`, 'User-Agent': 'browser', Cookie: key },
      data: { chat: 'private decision' },
    },
    user: { id: 'user-1', email: 'private@example.test' },
    exception: { values: [{ type: 'Error', value: 'private decision', stacktrace: { frames: [] } }] },
    extra: { response: 'private decision' },
    breadcrumbs: [{ message: 'private decision' }],
  };

  const result = scrubSentryEvent(event);
  const serialized = JSON.stringify(result);
  expect(serialized).not.toContain('private decision');
  expect(serialized).not.toContain('private-token');
  expect(serialized).not.toContain(key);
  expect(serialized).not.toContain('private@example.test');
  expect(result.user).toEqual({ id: 'user-1' });
  expect(result.request.headers).toEqual({ 'User-Agent': 'browser' });
  expect(result.exception.values[0].type).toBe('Error');
  expect(result.exception.values[0].stacktrace).toEqual({ frames: [] });
});

test('breadcrumb scrubber drops console and fetch bodies but keeps useful metadata', () => {
  const consoleResult = scrubSentryBreadcrumb({ category: 'console', message: 'private decision', data: { arguments: ['private'] } });
  expect(consoleResult.message).toBe('Console details suppressed');
  expect(consoleResult.data).toBeUndefined();

  const fetchResult = scrubSentryBreadcrumb({
    category: 'fetch',
    type: 'http',
    message: 'private decision',
    data: {
      method: 'POST',
      status_code: 500,
      url: 'https://jaspen.ai/s/private-token',
      request_body: 'private decision',
      response_body: 'private decision',
    },
  });
  expect(fetchResult).toEqual(expect.objectContaining({
    message: undefined,
    data: { method: 'POST', status_code: 500, url: `https://jaspen.ai/s/${REDACTED}` },
  }));
});
