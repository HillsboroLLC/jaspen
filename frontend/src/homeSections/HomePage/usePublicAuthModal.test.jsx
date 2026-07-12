import React from 'react';
import { render, screen } from '@testing-library/react';
import usePublicAuthModal from './usePublicAuthModal';

jest.mock('./StrategyAccessCard', () => function MockStrategyAccessCard(props) {
  return (
    <div
      data-testid="strategy-access-card"
      data-flow={props.initialFlowMode}
      data-plan={props.initialPlan}
    >
      <button type="button">Sign in</button>
      <button type="button">Create account</button>
    </div>
  );
});

function Harness() {
  const { AuthModalPortal } = usePublicAuthModal();
  return <>{AuthModalPortal}</>;
}

afterEach(() => {
  document.body.innerHTML = '';
  window.history.pushState({}, '', '/');
  jest.restoreAllMocks();
});

describe('usePublicAuthModal', () => {
  it('opens the existing public auth card in signup mode for Decision Profile email CTAs', () => {
    window.history.pushState(
      {},
      '',
      '/?auth=signup&source=decision-profile-email&error=session_expired&signed_out=1&reason=idle'
    );

    render(<Harness />);

    const card = screen.getByTestId('strategy-access-card');
    expect(card).toHaveAttribute('data-flow', 'signup');
    expect(card).toHaveAttribute('data-plan', 'free');
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create account/i })).toBeInTheDocument();
    expect(window.location.search).toBe('?source=decision-profile-email');
  });

  it('opens signin for the older auth=1 public entry pattern', () => {
    window.history.pushState({}, '', '/?auth=1');

    render(<Harness />);

    expect(screen.getByTestId('strategy-access-card')).toHaveAttribute('data-flow', 'signin');
    expect(window.location.search).toBe('');
  });

  it('renders the same entry card on a narrow mobile viewport', () => {
    Object.defineProperty(window, 'innerWidth', { configurable: true, value: 390 });
    window.history.pushState({}, '', '/?auth=signup&source=decision-profile-email');

    render(<Harness />);

    expect(screen.getByTestId('strategy-access-card')).toHaveAttribute('data-flow', 'signup');
  });
});
