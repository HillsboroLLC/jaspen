import React from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import Walkthrough from './Walkthrough';
import { markFeatureSeen } from './guidedDecisionState';

describe('Walkthrough composer ownership', () => {
  const NativeMutationObserver = global.MutationObserver;

  beforeEach(() => {
    jest.useFakeTimers();
    localStorage.clear();
    Object.defineProperty(HTMLElement.prototype, 'offsetParent', {
      configurable: true,
      get() { return document.body; },
    });
    jest.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue({
      top: 100, left: 100, right: 500, bottom: 180, width: 400, height: 80,
    });
    global.MutationObserver = class {
      observe() {}
      disconnect() {}
    };
  });

  afterEach(() => {
    jest.runOnlyPendingTimers();
    jest.useRealTimers();
    jest.restoreAllMocks();
    global.MutationObserver = NativeMutationObserver;
    document.body.innerHTML = '';
  });

  test('typing dismisses the Add context tip without consuming the message', () => {
    const user = { id: 'coach-user' };
    markFeatureSeen(user, 'chat');
    markFeatureSeen(user, 'objective');
    document.body.innerHTML = `
      <form class="jas-chat-input-area"><input aria-label="Decision message" /></form>
      <div class="jas-connector-context-tags">Jira</div>
    `;
    const input = screen.getByLabelText('Decision message');
    const host = document.createElement('div');
    document.body.appendChild(host);
    render(<Walkthrough user={user} />, { container: host });

    act(() => { jest.advanceTimersByTime(750); });
    const tipTitle = screen.getByText('Add context.');
    expect(tipTitle).toBeInTheDocument();
    expect(tipTitle.closest('div')).toHaveStyle({ pointerEvents: 'none' });
    expect(screen.getByRole('button', { name: 'Got it' })).toHaveStyle({ pointerEvents: 'auto' });

    fireEvent.input(input, { target: { value: 'Score this now' } });
    expect(input).toHaveValue('Score this now');
    expect(screen.queryByText('Add context.')).not.toBeInTheDocument();
  });
});
