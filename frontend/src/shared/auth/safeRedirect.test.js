import { safeInternalPath } from './safeRedirect';

const FALLBACK = '/fallback';

const rejectedPaths = [
  '//evil.example',
  '/\\evil.example',
  '/\\/evil.example',
  '/\t/evil.example',
  '/\n/evil.example',
  '/.//evil.example',
  '/..//evil.example',
  '/x/..//evil.example',
  '/%2e%2e//evil.example',
  '/%2F%2Fevil.example',
  '/%5Cevil.example',
  '/%252F%252Fevil.example',
  'https://evil.example',
  'javascript:alert(1)',
  'evil.example',
  ' //evil.example',
  '///evil.example',
  '/%5C%5Cevil.example',
  '/%09/evil.example',
  '/%00',
  '/%2525252F%2525252Fevil.example',
  '/%ZZ',
  '/%E0%A4%A',
  '',
  null,
  42,
];

const acceptedPaths = [
  '/new',
  '/new?sid=abc123',
  '/?auth=1',
  '/account?tab=plans',
  '/account?tab=plans#billing',
  '/decision-profile',
  '/connectors-manage?filter=active',
  '/limited-time/client-decisions?limited_time_checkout=resume',
  '/limited-time/strategic-planning?limited_time_checkout=resume&verified=1',
  '/new?ref=https://example.com//path',
  '/new?next=%2Fnew%3Fa%3D1',
  '/s/abc%20def',
  '/s/abc-123_DEF',
];

describe('safeInternalPath', () => {
  test.each(rejectedPaths)('returns the fallback for %p', (candidate) => {
    expect(safeInternalPath(candidate, FALLBACK)).toBe(FALLBACK);
  });

  test.each(acceptedPaths)('returns %p unchanged', (candidate) => {
    expect(safeInternalPath(candidate, FALLBACK)).toBe(candidate);
  });
});
