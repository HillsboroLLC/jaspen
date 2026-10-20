function inviteOrigin() {
  if (typeof window === 'undefined') return 'https://jaspen.ai';
  const host = String(window.location.hostname || '').toLowerCase();
  if (!host || host === 'localhost' || host === '127.0.0.1') return window.location.origin;
  return 'https://jaspen.ai';
}

const SIGNUP_REFERRAL_STORAGE_KEY = 'jaspen_signup_referral';
const SIGNUP_REFERRAL_TTL_MS = 60 * 24 * 60 * 60 * 1000;
const REFERRAL_QUERY_KEYS = ['referral_code', 'invite_code', 'ref', 'invite'];

function referralCodeFromUrl() {
  if (typeof window === 'undefined') return '';
  try {
    const params = new URLSearchParams(window.location.search || '');
    for (const key of REFERRAL_QUERY_KEYS) {
      const code = String(params.get(key) || '').trim();
      if (code) return code;
    }
  } catch (error) {
    console.debug('Failed reading referral code from URL:', error);
  }
  return '';
}

function readSavedSignupReferralCode() {
  if (typeof window === 'undefined') return '';
  try {
    const saved = JSON.parse(window.localStorage.getItem(SIGNUP_REFERRAL_STORAGE_KEY) || 'null');
    const code = String(saved?.code || '').trim();
    if (!code || Number(saved?.expiresAt || 0) <= Date.now()) {
      window.localStorage.removeItem(SIGNUP_REFERRAL_STORAGE_KEY);
      return '';
    }
    return code;
  } catch (error) {
    try {
      window.localStorage.removeItem(SIGNUP_REFERRAL_STORAGE_KEY);
    } catch (storageError) {
      // Storage is unavailable; there is no persisted referral to return.
    }
    return '';
  }
}

export function getSignupReferralCode() {
  const urlCode = referralCodeFromUrl();
  if (urlCode) {
    try {
      window.localStorage.setItem(SIGNUP_REFERRAL_STORAGE_KEY, JSON.stringify({
        code: urlCode,
        expiresAt: Date.now() + SIGNUP_REFERRAL_TTL_MS,
      }));
    } catch (error) {
      // Storage can be unavailable in private browsing; the current URL still works.
    }
    return urlCode;
  }
  return readSavedSignupReferralCode() || null;
}

export function clearSignupReferralCode() {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.removeItem(SIGNUP_REFERRAL_STORAGE_KEY);
  } catch (error) {
    // Ignore unavailable storage after signup has otherwise succeeded.
  }
}

export function addSignupReferralCodeToParams(params) {
  const referralCode = getSignupReferralCode();
  if (referralCode) params.set('referral_code', referralCode);
  return params;
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
