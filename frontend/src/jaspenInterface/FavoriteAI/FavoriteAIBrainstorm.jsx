import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
  const [returnedText, setReturnedText] = useState('');
  const [copyError, setCopyError] = useState(false);
  const [returnNudge, setReturnNudge] = useState(false);
  const previewRef = useRef(null);
  const pasteRef = useRef(null);
  const awaitingReturnRef = useRef(false);
  const leftForProviderRef = useRef(false);

  const provider = PROVIDERS[providerId];
  const copiedPrompt = useMemo(
    () => buildCopiedPrompt(projectSummary, includeSummary),
    [includeSummary, projectSummary]
  );

  const chooseProvider = useCallback((nextProviderId) => {
    setProviderId(nextProviderId);
    saveProvider(nextProviderId);
  }, []);

  const showDialog = useCallback((nextProviderId, nextStep = 'start') => {
    if (nextProviderId) chooseProvider(nextProviderId);
    setStep(nextStep);
    setCopyError(false);
    setReturnNudge(false);
    setOpen(true);
  }, [chooseProvider]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('keydown', onKeyDown);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [open]);

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

  const openProvider = useCallback(() => {
    markProviderTrip();
    window.open(provider.url, '_blank', 'noopener,noreferrer');
    setOpen(false);
  }, [markProviderTrip, provider.url]);

  const copyAndOpen = async () => {
    setCopyError(false);
    try {
      await navigator.clipboard.writeText(copiedPrompt);
      openProvider();
    } catch (_) {
      setCopyError(true);
      requestAnimationFrame(() => {
        previewRef.current?.focus();
        previewRef.current?.select();
      });
    }
  };

  const addToJaspen = () => {
    const trimmed = returnedText.trim();
    if (!trimmed) {
      pasteRef.current?.focus();
      return;
    }
    onAddToComposer(labelReturnedThinking(providerId, trimmed));
    setReturnedText('');
    setOpen(false);
    setReturnNudge(false);
  };

  return (
    <>
      <div className="favorite-ai-launchers">
        {PROVIDER_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className={`gd-nav-icon favorite-ai-provider-icon favorite-ai-provider-icon--${id}`}
            style={id === 'chatgpt' ? undefined : { color: PROVIDERS[id].color }}
            onClick={() => showDialog(id)}
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
        style={providerId === 'chatgpt' ? undefined : { color: provider.color }}
        onClick={() => showDialog(providerId)}
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
            onClick={() => showDialog(providerId, 'return')}
          >
            Bring your {provider.name} thinking back to Jaspen
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
          <div style={S.backdrop} onClick={() => setOpen(false)} />
          <div style={{ ...S.wizardCard, maxWidth: '680px' }} className="gd-modal-card favorite-ai-modal">
            <button
              type="button"
              style={S.closeBtn}
              onClick={() => setOpen(false)}
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
                    <span
                      className={`favorite-ai-provider-logo favorite-ai-provider-logo--${id}`}
                      style={id === 'chatgpt' ? undefined : { color: PROVIDERS[id].color }}
                    >
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
                  <label className="favorite-ai-toggle">
                    <input
                      type="checkbox"
                      checked={includeSummary}
                      onChange={(event) => setIncludeSummary(event.target.checked)}
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
                    value={copiedPrompt}
                    readOnly
                    rows={includeSummary ? 13 : 10}
                  />
                  {copyError && (
                    <div className="favorite-ai-copy-error" role="alert">
                      <span>Clipboard access failed. The prompt is selected so you can copy it manually.</span>
                      <button type="button" onClick={openProvider}>Open {provider.name}</button>
                    </div>
                  )}
                </>
              ) : (
                <>
                  <p className="favorite-ai-return-help">
                    Paste the useful parts of your {provider.name} brainstorm. Jaspen will place them in the composer for you to review before sending.
                  </p>
                  <label className="favorite-ai-preview-label" htmlFor="favorite-ai-return-text">
                    Your brainstorm
                  </label>
                  <textarea
                    id="favorite-ai-return-text"
                    ref={pasteRef}
                    className="favorite-ai-preview favorite-ai-return-text"
                    value={returnedText}
                    onChange={(event) => setReturnedText(event.target.value)}
                    placeholder={`Paste your ${provider.name} summary here`}
                    rows={10}
                  />
                </>
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
                <button type="button" className="favorite-ai-primary gd-btn gd-btn--primary" onClick={addToJaspen}>
                  Add to Jaspen
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
