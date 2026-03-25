function inviteOrigin() {
  if (typeof window === 'undefined') return 'https://jaspen.ai';
  const host = String(window.location.hostname || '').toLowerCase();
  if (!host || host === 'localhost' || host === '127.0.0.1') return window.location.origin;
  return 'https://jaspen.ai';
}

export function getShortInviteCode(referralCode, length = 10) {
  const normalized = String(referralCode || '').replace(/[^a-zA-Z0-9]/g, '');
  if (!normalized) return '';
  return normalized.slice(0, length).toLowerCase();
}

export function buildInviteLink(referralCode, length = 10) {
  const shortCode = getShortInviteCode(referralCode, length);
  if (!shortCode) return '';
  return `${inviteOrigin()}/?ref=${encodeURIComponent(shortCode)}`;
}

export function buildInviteDisplay(referralCode, length = 10) {
  const shortCode = getShortInviteCode(referralCode, length);
  if (!shortCode) return '';
  return `jaspen.ai/?ref=${shortCode}`;
}
