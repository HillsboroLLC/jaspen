// Single source of truth for the key that carries anonymous homepage intake
// context through signup/login into the authenticated workspace.
//
// Lifecycle: written by the homepage hero on a successful "send to Jaspen";
// consumed (and cleared) by the auth handoff on a successful
// conversation/start; recovered by /new as a composer prefill if the handoff
// failed — the key is only ever cleared after the context has demonstrably
// reached its destination. sessionStorage (not localStorage) on purpose:
// pasted decision context can be sensitive and should not outlive the tab.
//
// Canonical join contract: the homepage may run a multi-turn Q&A, but there
// is exactly ONE joined string that ever gets analyzed or handed off — built
// with joinTurns() below. Never inject labels ("Goal:", "Answer:", etc.) into
// the join; several spec keywords are plain words like "goal" or "risk", and
// a label would tick a readiness category that the user's own words did not
// actually satisfy. Keep this in sync with backend MAX_USER_MESSAGE_LENGTH
// (backend/app/routes/ai_agent.py) — it's duplicated here only as a
// client-side soft guide, the backend value is always the enforced one.
export const PENDING_CONTEXT_STORAGE_KEY = 'jaspen_pending_intake_context';
const PENDING_THREAD_ID_STORAGE_KEY = 'jaspen_pending_intake_thread_id';

export const MAX_INTAKE_LENGTH_HINT = 12000;

export function joinTurns(turns) {
  return (turns || [])
    .map((t) => String(t || '').trim())
    .filter(Boolean)
    .join('\n\n');
}

export function readPendingIntakeContext() {
  let raw = '';
  try {
    raw = window.sessionStorage.getItem(PENDING_CONTEXT_STORAGE_KEY) || '';
  } catch {
    return '';
  }
  const trimmed = raw.trim();
  if (!trimmed) return '';
  // Defensive only: the write path always stores a plain canonical string.
  // If an older or different build ever stored a structured turns array
  // instead, recover it the same way rather than losing the user's context.
  if (trimmed.startsWith('[') || trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return joinTurns(parsed);
      if (Array.isArray(parsed?.turns)) return joinTurns(parsed.turns);
    } catch {
      // Not actually JSON — fall through and treat as a plain string.
    }
  }
  return trimmed;
}

export function clearPendingIntakeContext() {
  try {
    window.sessionStorage.removeItem(PENDING_CONTEXT_STORAGE_KEY);
  } catch { /* sessionStorage unavailable */ }
}

export function writePendingIntakeContext(value) {
  try {
    window.sessionStorage.setItem(PENDING_CONTEXT_STORAGE_KEY, value);
  } catch { /* sessionStorage unavailable */ }
}

// --- Handoff idempotency -----------------------------------------------
//
// A visitor's first message to Jaspen is more valuable in this design (it can
// be a whole multi-turn interview), which raises the cost of an accidental
// double-submission (double-click, a retried login) creating two threads.
// Two mechanisms:
//  1. A client-generated, persisted thread_id reused across retries so
//     conversation/start always upserts the SAME thread instead of minting a
//     new one each attempt.
//  2. An in-flight guard shared across every call site (email signup, email
//     login, Google OAuth callback) so concurrent attempts share one promise
//     instead of firing parallel requests.

function randomThreadId() {
  const cryptoObj = window.crypto || window.msCrypto;
  const bytes = new Uint8Array(8);
  if (cryptoObj?.getRandomValues) {
    cryptoObj.getRandomValues(bytes);
  } else {
    for (let i = 0; i < bytes.length; i += 1) bytes[i] = Math.floor(Math.random() * 256);
  }
  const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
  return `thread_${hex}`;
}

export function getOrCreatePendingThreadId() {
  try {
    const existing = window.sessionStorage.getItem(PENDING_THREAD_ID_STORAGE_KEY);
    if (existing) return existing;
    const id = randomThreadId();
    window.sessionStorage.setItem(PENDING_THREAD_ID_STORAGE_KEY, id);
    return id;
  } catch {
    return randomThreadId();
  }
}

export function clearPendingIntakeThreadId() {
  try {
    window.sessionStorage.removeItem(PENDING_THREAD_ID_STORAGE_KEY);
  } catch { /* ignore */ }
}

let _inFlightHandoffPromise = null;

// Wrap the entire auth-handoff body in this so a double-click or a retry
// from a second call site (signup vs login vs Google callback) never runs
// the handoff twice concurrently — they share the one in-flight promise.
export function runExclusiveHandoff(fn) {
  if (_inFlightHandoffPromise) return _inFlightHandoffPromise;
  _inFlightHandoffPromise = Promise.resolve()
    .then(fn)
    .finally(() => {
      _inFlightHandoffPromise = null;
    });
  return _inFlightHandoffPromise;
}
