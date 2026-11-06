const MALFORMED_PERCENT_ESCAPE = /%(?![0-9A-Fa-f]{2})/;

function hasControlCharacter(value) {
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code <= 0x1F || code === 0x7F) return true;
  }
  return false;
}

function unsafePathForm(path) {
  return (
    !path.startsWith('/')
    || path.startsWith('//')
    || path.includes('\\')
    || hasControlCharacter(path)
    || path.split('/').some((segment) => segment === '.' || segment === '..')
  );
}

export function safeInternalPath(candidate, fallback = '/new') {
  if (typeof candidate !== 'string' || candidate.length === 0) return fallback;
  if (!candidate.startsWith('/') || candidate.startsWith('//')) return fallback;
  if (hasControlCharacter(candidate)) return fallback;

  const separatorIndex = candidate.search(/[?#]/);
  const rawPath = separatorIndex === -1 ? candidate : candidate.slice(0, separatorIndex);
  const forms = [rawPath];
  let current = rawPath;
  let stable = false;

  for (let round = 0; round < 3; round += 1) {
    if (MALFORMED_PERCENT_ESCAPE.test(current)) return fallback;
    let decoded;
    try {
      decoded = decodeURIComponent(current);
    } catch {
      return fallback;
    }
    forms.push(decoded);
    if (decoded === current) {
      stable = true;
      break;
    }
    current = decoded;
  }

  if (!stable || forms.some(unsafePathForm)) return fallback;

  try {
    const base = 'https://jaspen.invalid';
    if (new URL(candidate, base).origin !== base) return fallback;
  } catch {
    return fallback;
  }

  return candidate;
}
