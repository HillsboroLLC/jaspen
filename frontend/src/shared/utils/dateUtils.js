/**
 * dateUtils.js
 * Timezone-aware date formatting utilities.
 * All functions read the user's timezone from the browser automatically
 * via Intl.DateTimeFormat().resolvedOptions().timeZone.
 */

export function getUserTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

/**
 * Parse a date value into a Date object, treating bare datetime strings
 * (no timezone offset, no Z) as UTC. The backend stores all timestamps via
 * datetime.utcnow().isoformat() which omits the "Z" — without this fix,
 * JavaScript incorrectly treats them as local time.
 */
function parseUtcDate(value) {
  if (!value) return null;
  if (value instanceof Date) return value;
  const s = String(value).trim();
  // If already has timezone info (Z, +HH:MM, -HH:MM), parse as-is.
  if (/[Zz]$/.test(s) || /[+-]\d{2}:\d{2}$/.test(s)) {
    return new Date(s);
  }
  // Bare datetime string (e.g. "2026-05-10T20:02:00" or "2026-05-10T20:02:00.123456"):
  // treat as UTC by appending Z.
  if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) {
    return new Date(s + 'Z');
  }
  // Fallback for date-only strings or anything else.
  return new Date(s);
}

/**
 * Format a date/timestamp as a short date: "May 9, 2026"
 */
export function formatDate(value, options = {}) {
  if (!value) return '';
  try {
    const date = parseUtcDate(value);
    if (!date || Number.isNaN(date.getTime())) return '';
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: getUserTimezone(),
      ...options,
    });
  } catch {
    return '';
  }
}

/**
 * Format a date/timestamp with time: "May 9, 2026, 2:34 PM"
 */
export function formatDateTime(value, options = {}) {
  if (!value) return '';
  try {
    const date = parseUtcDate(value);
    if (!date || Number.isNaN(date.getTime())) return '';
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      timeZone: getUserTimezone(),
      ...options,
    });
  } catch {
    return '';
  }
}

/**
 * Format a timestamp as a smart relative label:
 * "Today", "Yesterday", "3 days ago", or "May 3, 2026"
 */
export function formatSmartDate(value) {
  if (!value) return '';
  try {
    const date = parseUtcDate(value);
    if (!date || Number.isNaN(date.getTime())) return '';
    const tz = getUserTimezone();
    const now = new Date();
    const todayStr = now.toLocaleDateString('en-US', { timeZone: tz });
    const dateStr = date.toLocaleDateString('en-US', { timeZone: tz });
    if (dateStr === todayStr) return 'Today';
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (dateStr === yesterday.toLocaleDateString('en-US', { timeZone: tz })) return 'Yesterday';
    const diffDays = Math.round((now - date) / (1000 * 60 * 60 * 24));
    if (diffDays > 0 && diffDays < 7) return `${diffDays} days ago`;
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: tz,
    });
  } catch {
    return '';
  }
}

/**
 * Given the last credit reset date, return the NEXT reset date formatted.
 * e.g. credits_reset_at = "2026-05-09" → "Jun 9, 2026"
 */
export function formatNextResetDate(lastResetValue) {
  if (!lastResetValue) return 'your next billing date';
  try {
    const last = parseUtcDate(lastResetValue);
    if (!last || Number.isNaN(last.getTime())) return 'your next billing date';
    const next = new Date(last);
    next.setMonth(next.getMonth() + 1);
    return next.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric',
      timeZone: getUserTimezone(),
    });
  } catch {
    return 'your next billing date';
  }
}

/**
 * Format a timestamp as time only: "2:34 PM"
 */
export function formatTime(value, options = {}) {
  if (!value) return '';
  try {
    const date = parseUtcDate(value);
    if (!date || Number.isNaN(date.getTime())) return '';
    return date.toLocaleTimeString('en-US', {
      hour: 'numeric',
      minute: '2-digit',
      timeZone: getUserTimezone(),
      ...options,
    });
  } catch {
    return '';
  }
}
