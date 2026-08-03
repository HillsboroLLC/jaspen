import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../shared/auth/AuthContext';
import { authFetch } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import './RankThemPromoModal.css';

const SEEN_KEY = 'jaspen.promo.rankThem.lastSeen';
const DISMISSED_KEY = 'jaspen.promo.rankThem.dismissed';
// Once a week is enough to be noticed and not enough to be resented. A visitor
// who closes it deliberately is not asked again at all.
const REAPPEAR_AFTER_MS = 7 * 24 * 60 * 60 * 1000;
// Fallbacks only. The server sends a frequency block, and it wins when present
// so pacing can be retuned without a deploy.
const APPEAR_AFTER_MS = 12000;
const HEADLINE = 'RANK THEM';

function readTimestamp(key) {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? Number(raw) || 0 : 0;
  } catch {
    return 0; // private browsing, or storage disabled
  }
}

function writeTimestamp(key) {
  try {
    window.localStorage.setItem(key, String(Date.now()));
  } catch {
    /* nothing to do: the modal simply shows again next visit */
  }
}

export function shouldOfferPromo(now = Date.now()) {
  if (readTimestamp(DISMISSED_KEY)) return false;
  const lastSeen = readTimestamp(SEEN_KEY);
  return !lastSeen || now - lastSeen > REAPPEAR_AFTER_MS;
}

export default function RankThemPromoModal() {
  const navigate = useNavigate();
  const { user } = useAuth();
  const [promo, setPromo] = useState(null);
  const [open, setOpen] = useState(false);
  const closeRef = useRef(null);
  const dialogRef = useRef(null);
  const returnFocusRef = useRef(null);

  // Someone who already bought the offer must never be sold it again. The
  // flag is not on the session user, so a signed-in visitor is checked against
  // billing; a signed-out one cannot have bought it on this device anyway.
  const [alreadyPurchased, setAlreadyPurchased] = useState(false);
  // Nothing opens until this settles. Otherwise a buyer whose billing check
  // answers after the catalog sees the modal flash before it is suppressed.
  const [purchaseChecked, setPurchaseChecked] = useState(false);

  useEffect(() => {
    if (!user) { setAlreadyPurchased(false); setPurchaseChecked(true); return undefined; }
    setPurchaseChecked(false);
    let cancelled = false;
    authFetch(`${API_BASE}/api/v1/billing/status`, { credentials: 'include' })
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled) return;
        if (data?.has_300k_limited_time) setAlreadyPurchased(true);
        setPurchaseChecked(true);
      })
      .catch(() => {
        // Leave the promotion visible rather than hiding it on a network blip.
        if (!cancelled) setPurchaseChecked(true);
      });
    return () => { cancelled = true; };
  }, [user]);

  useEffect(() => {
    let cancelled = false;
    if (alreadyPurchased || !shouldOfferPromo()) return undefined;

    fetch(`${API_BASE}/api/v1/billing/catalog`)
      .then((response) => (response.ok ? response.json() : null))
      .then((data) => {
        if (cancelled || !data?.promotion?.active) return;
        setPromo(data.promotion);
      })
      .catch(() => {
        /* the promotion simply does not show */
      });
    return () => { cancelled = true; };
  }, [alreadyPurchased]);

  useEffect(() => {
    if (!promo || !purchaseChecked || alreadyPurchased) return undefined;
    const delayMs = Number(promo.frequency?.delay_seconds) > 0
      ? Number(promo.frequency.delay_seconds) * 1000
      : APPEAR_AFTER_MS;
    const timer = window.setTimeout(() => {
      returnFocusRef.current = document.activeElement;
      setOpen(true);
      writeTimestamp(SEEN_KEY);
    }, delayMs);
    return () => window.clearTimeout(timer);
  }, [promo, purchaseChecked, alreadyPurchased]);

  const close = useCallback(({ permanently = false } = {}) => {
    if (permanently) writeTimestamp(DISMISSED_KEY);
    setOpen(false);
    // Send focus back where it was, so a keyboard user is not dropped at the
    // top of the document.
    if (returnFocusRef.current?.focus) returnFocusRef.current.focus();
  }, []);

  useEffect(() => {
    if (!open) return undefined;
    closeRef.current?.focus();

    const onKeyDown = (event) => {
      if (event.key === 'Escape') {
        close({ permanently: true });
        return;
      }
      if (event.key !== 'Tab') return;
      // Keep Tab inside the dialog while it is open.
      const focusable = dialogRef.current?.querySelectorAll(
        'button, a[href], input, [tabindex]:not([tabindex="-1"])',
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

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [open, close]);

  if (!open || !promo) return null;

  const goToOffer = () => {
    writeTimestamp(DISMISSED_KEY); // they acted; stop asking
    setOpen(false);
    navigate(promo.campaign_path);
  };

  return (
    <div
      className="rank-them-backdrop"
      onMouseDown={(event) => { if (event.target === event.currentTarget) close({ permanently: true }); }}
    >
      <div
        className="rank-them-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="rank-them-title"
        aria-describedby="rank-them-body"
        ref={dialogRef}
      >
        <button
          type="button"
          className="rank-them-close"
          onClick={() => close({ permanently: true })}
          aria-label="Close promotion"
          ref={closeRef}
        >
          ×
        </button>
        <p className="rank-them-eyebrow">Limited-time offer</p>
        <h2 id="rank-them-title">{HEADLINE}</h2>
        <p id="rank-them-body">
          Limited time. Limited resources. Too many priorities.
        </p>
        <p className="rank-them-body-detail">
          Rank your initiatives so you know what to focus on first, what can wait, and why.
        </p>
        <p className="rank-them-price">
          <strong>300,000 AI-powered usage credits for $999.</strong>
          <span className="rank-them-terms">One payment. No subscription. Credits never expire.</span>
        </p>
        <div className="rank-them-actions">
          <button type="button" className="rank-them-primary" onClick={goToOffer}>
            {'Let\u2019s rank my priorities'}
          </button>
          <button type="button" className="rank-them-secondary" onClick={() => close({ permanently: true })}>
            Not now
          </button>
        </div>
      </div>
    </div>
  );
}
