const ISO_CALENDAR_DATE = /^\d{4}-\d{2}-\d{2}$/;

// Date inputs must never turn legacy or display-only text into a proposed date.
// The server remains authoritative for whether a plan write is accepted.
export function toDateInputValue(value) {
  const text = typeof value === 'string' ? value : '';
  if (!ISO_CALENDAR_DATE.test(text)) return '';
  const [year, month, day] = text.split('-').map(Number);
  const parsed = new Date(Date.UTC(year, month - 1, day));
  if (
    parsed.getUTCFullYear() !== year
    || parsed.getUTCMonth() !== month - 1
    || parsed.getUTCDate() !== day
  ) return '';
  return text;
}
