import { useCallback, useEffect, useState } from 'react';
import { createPortal } from 'react-dom';
import StrategyAccessCard from './StrategyAccessCard';

export default function usePublicAuthModal(heroContext = '') {
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const [authModalFlow, setAuthModalFlow] = useState('signin');
  const [authModalPlan, setAuthModalPlan] = useState('free');

  const openAuthModal = useCallback((flow = 'signin', plan = 'free') => {
    setAuthModalFlow(flow);
    setAuthModalPlan(plan);
    setAuthModalOpen(true);
  }, []);

  const closeAuthModal = useCallback(() => {
    setAuthModalOpen(false);
  }, []);

  useEffect(() => {
    if (typeof window === 'undefined') return;
    const params = new URLSearchParams(window.location.search || '');
    const authIntent = String(params.get('auth') || '').trim().toLowerCase();
    if (!authIntent || (authIntent !== '1' && authIntent !== 'signup' && authIntent !== 'signin')) return;

    openAuthModal(authIntent === 'signup' ? 'signup' : 'signin');
    params.delete('auth');
    const source = String(params.get('source') || '').trim().toLowerCase();
    if (source === 'decision-profile-email' || source === 'decision-planning-toolkit-email') {
      params.delete('error');
      params.delete('signed_out');
      params.delete('reason');
    }
    const nextSearch = params.toString();
    const nextUrl = `${window.location.pathname}${nextSearch ? `?${nextSearch}` : ''}${window.location.hash || ''}`;
    window.history.replaceState({}, '', nextUrl);
  }, [openAuthModal]);

  const AuthModalPortal = authModalOpen && typeof document !== 'undefined'
    ? createPortal(
        <div
          className="sac-modal-backdrop"
          onMouseDown={(event) => {
            if (event.target === event.currentTarget) closeAuthModal();
          }}
        >
          <div className="sac-modal-shell">
            <button
              type="button"
              className="sac-modal-close"
              onClick={closeAuthModal}
              aria-label="Close"
            >
              <i className="fa-solid fa-xmark" aria-hidden="true"></i>
            </button>
            <StrategyAccessCard
              key={`${authModalFlow}-${authModalPlan}`}
              initialFlowMode={authModalFlow}
              initialPlan={authModalPlan}
              heroContext={heroContext}
            />
          </div>
        </div>,
        document.body
      )
    : null;

  return { openAuthModal, AuthModalPortal };
}
