import { isDecisionProfileEmailEntry } from './AuthContext';

afterEach(() => {
  window.history.pushState({}, '', '/');
});

describe('Decision Profile email auth entry', () => {
  it('recognizes the clean signup source used by the email CTA', () => {
    window.history.pushState({}, '', '/?auth=signup&source=decision-profile-email');

    expect(isDecisionProfileEmailEntry()).toBe(true);
  });

  it('does not treat generic signup or stale session URLs as the email entry', () => {
    window.history.pushState({}, '', '/?auth=signup&error=session_expired');
    expect(isDecisionProfileEmailEntry()).toBe(false);

    window.history.pushState({}, '', '/?auth=1&source=decision-profile-email');
    expect(isDecisionProfileEmailEntry()).toBe(false);
  });
});
