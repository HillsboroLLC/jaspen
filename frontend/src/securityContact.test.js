import fs from 'fs';
import path from 'path';

const securityTxtPath = path.join(
  process.cwd(),
  'public',
  '.well-known',
  'security.txt',
);

describe('security contact publication', () => {
  const contents = fs.readFileSync(securityTxtPath, 'utf8');

  test('publishes the required RFC 9116 fields', () => {
    expect(contents).toContain('Contact: mailto:security@jaspen.ai');
    expect(contents).toContain(
      'Canonical: https://jaspen.ai/.well-known/security.txt',
    );
    expect(contents).not.toMatch(/^Policy:/m);
  });

  test('has a future expiration date', () => {
    const expires = contents.match(/^Expires:\s*(.+)$/m);
    expect(expires).not.toBeNull();
    expect(Number.isNaN(Date.parse(expires[1]))).toBe(false);
    expect(Date.parse(expires[1])).toBeGreaterThan(Date.now());
  });
});
