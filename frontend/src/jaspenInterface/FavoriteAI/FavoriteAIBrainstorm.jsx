import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import * as S from '../GuidedDecision/guidedDecisionStyles';
import ProviderLogo from './ProviderLogo';
import {
  buildCopiedPrompt,
  labelReturnedThinking,
  PROVIDER_IDS,
  PROVIDERS,
} from './favoriteAI';
import './FavoriteAIBrainstorm.css';

const STORAGE_KEY = 'jaspen.brainstormProvider';
const TOOLTIP = 'Brainstorm with your favorite AI tool';

function readSavedProvider() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY);
    return PROVIDERS[saved] ? saved : 'chatgpt';
  } catch (_) {
    return 'chatgpt';
  }
}

function saveProvider(providerId) {
  try { localStorage.setItem(STORAGE_KEY, providerId); } catch (_) { /* storage is optional */ }
}

export default function FavoriteAIBrainstorm({ projectSummary, onAddToComposer }) {
  const [providerId, setProviderId] = useState(readSavedProvider);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState('start');
  const [includeSummary, setIncludeSummary] = useState(false);
  const [promptText, setPromptText] = useState(() => buildCopiedPrompt(projectSummary, false));
  const [copyError, setCopyError] = useState(false);
  const [popupError, setPopupError] = useState(false);
  const [returnNudge, setReturnNudge] = useState(false);
  const previewRef = useRef(null);
  const modalRef = useRef(null);
  const closeButtonRef = useRef(null);
  const lastTriggerRef = useRef(null);
  const awaitingReturnRef = useRef(false);
  const leftForProviderRef = useRef(false);

  const provider = PROVIDERS[providerId];
  const chooseProvider = useCallback((nextProviderId) => {
    setProviderId(nextProviderId);
    saveProvider(nextProviderId);
  }, []);

  const closeDialog = useCallback((restoreFocus = true) => {
    setOpen(false);
    if (restoreFocus) requestAnimationFrame(() => lastTriggerRef.current?.focus());
  }, []);

  const showDialog = useCallback((nextProviderId, nextStep = 'start', trigger = null) => {
    if (nextProviderId) chooseProvider(nextProviderId);
    lastTriggerRef.current = trigger || document.activeElement;
    setStep(nextStep);
    setCopyError(false);
    setPopupError(false);
    setReturnNudge(false);
    if (nextStep === 'start') setPromptText(buildCopiedPrompt(projectSummary, includeSummary));
    setOpen(true);
  }, [chooseProvider, includeSummary, projectSummary]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        closeDialog();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = modalRef.current?.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
      );
      if (!focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    requestAnimationFrame(() => closeButtonRef.current?.focus());
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [closeDialog, open]);

  useEffect(() => {
    const markLeft = () => {
      if (awaitingReturnRef.current) leftForProviderRef.current = true;
    };
    const offerReturn = () => {
      if (!awaitingReturnRef.current || !leftForProviderRef.current) return;
      awaitingReturnRef.current = false;
      leftForProviderRef.current = false;
      setReturnNudge(true);
    };
    const onVisibility = () => {
      if (document.visibilityState === 'hidden') markLeft();
      if (document.visibilityState === 'visible') offerReturn();
    };
    window.addEventListener('blur', markLeft);
    window.addEventListener('focus', offerReturn);
    document.addEventListener('visibilitychange', onVisibility);
    return () => {
      window.removeEventListener('blur', markLeft);
      window.removeEventListener('focus', offerReturn);
      document.removeEventListener('visibilitychange', onVisibility);
    };
  }, []);

  const markProviderTrip = useCallback(() => {
    awaitingReturnRef.current = true;
    leftForProviderRef.current = false;
    setReturnNudge(false);
  }, []);

  const openProviderWindow = useCallback(() => {
    try {
      const providerWindow = window.open(provider.url, '_blank');
      if (!providerWindow) return false;
      providerWindow.opener = null;
      markProviderTrip();
      return true;
    } catch (_) {
      return false;
    }
  }, [markProviderTrip, provider.url]);

  const openProvider = useCallback(() => {
    if (openProviderWindow()) closeDialog(false);
    else setPopupError(true);
  }, [closeDialog, openProviderWindow]);

  const copyAndOpen = async () => {
    setCopyError(false);
    setPopupError(false);
    let copyRequest;
    try {
      copyRequest = navigator.clipboard.writeText(promptText);
    } catch (_) {
      copyRequest = Promise.reject(_);
    }
    const providerOpened = openProviderWindow();
    try {
      await copyRequest;
      if (providerOpened) closeDialog(false);
      else setPopupError(true);
    } catch (_) {
      setCopyError(true);
      requestAnimationFrame(() => {
        previewRef.current?.focus();
        previewRef.current?.select();
      });
    }
  };

  const returnToComposer = () => {
    onAddToComposer(labelReturnedThinking(providerId, ''));
    closeDialog(false);
    setReturnNudge(false);
  };

  const toggleSummary = (checked) => {
    setIncludeSummary(checked);
    setPromptText(buildCopiedPrompt(projectSummary, checked));
  };

  return (
    <>
      <div className="favorite-ai-launchers">
        {PROVIDER_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className={`gd-nav-icon favorite-ai-provider-icon favorite-ai-provider-icon--${id}`}
            onClick={(event) => showDialog(id, 'start', event.currentTarget)}
            data-tooltip={TOOLTIP}
            aria-label={`Brainstorm with ${PROVIDERS[id].name}`}
          >
            <ProviderLogo provider={id} />
          </button>
        ))}
      </div>
      <button
        type="button"
        className={`gd-nav-icon favorite-ai-collapsed-icon favorite-ai-provider-icon--${providerId}`}
        onClick={(event) => showDialog(providerId, 'start', event.currentTarget)}
        data-tooltip={TOOLTIP}
        aria-label={TOOLTIP}
      >
        <ProviderLogo provider={providerId} />
      </button>

      {returnNudge && (
        <div className="favorite-ai-nudge" role="status">
          <button
            type="button"
            className="favorite-ai-nudge-copy"
            onClick={returnToComposer}
          >
            Continue in Jaspen with your {provider.name} summary
          </button>
          <button
            type="button"
            className="favorite-ai-nudge-close"
            onClick={() => setReturnNudge(false)}
            aria-label="Dismiss brainstorm return reminder"
          >
            ×
          </button>
        </div>
      )}

      {open && createPortal(
        <div
          className="favorite-ai-overlay"
          style={{ ...S.overlay, zIndex: 7000 }}
          role="dialog"
          aria-modal="true"
          aria-label="Brainstorm with your favorite AI tool"
        >
          <div style={S.backdrop} onClick={() => closeDialog()} />
          <div ref={modalRef} style={{ ...S.wizardCard, maxWidth: '680px' }} className="gd-modal-card favorite-ai-modal">
            <button
              ref={closeButtonRef}
              type="button"
              style={S.closeBtn}
              onClick={() => closeDialog()}
              aria-label="Close AI brainstorm dialog"
            >
              ×
            </button>

            <div className="favorite-ai-header">
              <p className="favorite-ai-eyebrow">Brainstorm elsewhere, evaluate here</p>
              <h2>{step === 'start' ? 'Brainstorm with your favorite AI' : 'Bring your thinking back'}</h2>
              <div className="favorite-ai-provider-tabs" aria-label="Choose an AI provider">
                {PROVIDER_IDS.map((id) => (
                  <button
                    key={id}
                    type="button"
                    className={id === providerId ? 'is-active' : ''}
                    onClick={() => chooseProvider(id)}
                    aria-pressed={id === providerId}
                  >
                    <span className={`favorite-ai-provider-logo favorite-ai-provider-logo--${id}`}>
                      <ProviderLogo provider={id} size={16} />
                    </span>
                    {PROVIDERS[id].name}
                  </button>
                ))}
              </div>
            </div>

            <div className="favorite-ai-body">
              {step === 'start' ? (
                <>
                  <aside className="favorite-ai-integration-note">
                    <strong>Exploring a more connected experience</strong>
                    <span>We're exploring deeper provider integrations to make brainstorming alongside Jaspen easier. For now, use the assistant you prefer and bring your summary back when you're ready.</span>
                  </aside>
                  <label className="favorite-ai-toggle">
                    <input
                      type="checkbox"
                      checked={includeSummary}
                      onChange={(event) => toggleSummary(event.target.checked)}
                    />
                    <span>Include this project's summary</span>
                  </label>
                  <p className="favorite-ai-privacy">
                    Off by default. Only the project title, options, and open questions shown in Jaspen are added when you turn this on.
                  </p>
                  <label className="favorite-ai-preview-label" htmlFor="favorite-ai-prompt-preview">
                    Prompt to copy
                  </label>
                  <textarea
                    id="favorite-ai-prompt-preview"
                    ref={previewRef}
                    className="favorite-ai-preview"
                    value={promptText}
                    onChange={(event) => setPromptText(event.target.value)}
                    rows={includeSummary ? 13 : 10}
                  />
                  <p className="favorite-ai-edit-help">Edit this prompt before copying if you want to change the emphasis or add context.</p>
                  {copyError && (
                    <div className="favorite-ai-copy-error" role="alert">
                      <span>Clipboard access failed. The prompt is selected so you can copy it manually, then continue in {provider.name}.</span>
                      <button type="button" onClick={openProvider}>Open {provider.name}</button>
                    </div>
                  )}
                  {popupError && !copyError && (
                    <div className="favorite-ai-copy-error" role="alert">
                      <span>The prompt was copied, but your browser blocked the new tab.</span>
                      <button type="button" onClick={openProvider}>Open {provider.name}</button>
                    </div>
                  )}
                </>
              ) : (
                <div className="favorite-ai-return-card">
                  <div className="favorite-ai-return-number" aria-hidden="true">1</div>
                  <p className="favorite-ai-return-help">
                    Ask {provider.name} for the structured Jaspen summary when you're ready to return.
                  </p>
                  <div className="favorite-ai-return-number" aria-hidden="true">2</div>
                  <p className="favorite-ai-return-help">
                    Continue to Jaspen, paste the summary into the existing composer, then review or edit it before sending. Jaspen never submits it automatically.
                  </p>
                </div>
              )}
            </div>

            <div className="favorite-ai-footer gd-wizard-footer">
              <button
                type="button"
                className="favorite-ai-step-link gd-back-link"
                onClick={() => setStep(step === 'start' ? 'return' : 'start')}
              >
                {step === 'start' ? 'Bring your thinking back' : 'Back to starting prompt'}
              </button>
              {step === 'start' ? (
                <button type="button" className="favorite-ai-primary gd-btn gd-btn--primary" onClick={copyAndOpen}>
                  Copy prompt and open {provider.name}
                </button>
              ) : (
                <button type="button" className="favorite-ai-primary gd-btn gd-btn--primary" onClick={returnToComposer}>
                  Continue in Jaspen
                </button>
              )}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
