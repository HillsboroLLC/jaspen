import {
  addSignupReferralCodeToParams,
  clearSignupReferralCode,
  getSignupReferralCode,
} from './inviteLink';

describe('signup referral persistence', () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.pushState({}, '', '/');
  });

  afterEach(() => {
    jest.restoreAllMocks();
  });

  it('keeps a URL referral available after navigation and adds it to Google start params', () => {
    window.history.pushState({}, '', '/?ref=abc123');
    expect(getSignupReferralCode()).toBe('abc123');

    window.history.pushState({}, '', '/pricing');
    expect(getSignupReferralCode()).toBe('abc123');

    const params = addSignupReferralCodeToParams(new URLSearchParams({ next: '/new' }));
    expect(params.get('referral_code')).toBe('abc123');
  });

  it('prefers the current URL and does not replace a saved code with an empty alias', () => {
    window.history.pushState({}, '', '/?invite=first');
    expect(getSignupReferralCode()).toBe('first');

    window.history.pushState({}, '', '/?ref=second');
    expect(getSignupReferralCode()).toBe('second');

    window.history.pushState({}, '', '/?ref=');
    expect(getSignupReferralCode()).toBe('second');
  });

  it('expires saved referrals after about 60 days and supports explicit clearing', () => {
    const now = 1_800_000_000_000;
    jest.spyOn(Date, 'now').mockReturnValue(now);
    window.history.pushState({}, '', '/?ref=temporary');
    expect(getSignupReferralCode()).toBe('temporary');

    window.history.pushState({}, '', '/');
    Date.now.mockReturnValue(now + (61 * 24 * 60 * 60 * 1000));
    expect(getSignupReferralCode()).toBeNull();

    window.history.pushState({}, '', '/?ref=clear-me');
    expect(getSignupReferralCode()).toBe('clear-me');
    window.history.pushState({}, '', '/');
    clearSignupReferralCode();
    expect(getSignupReferralCode()).toBeNull();
  });
});
