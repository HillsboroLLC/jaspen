import React, { useCallback, useEffect, useRef, useState } from 'react';
import { getCoachStarted, setCoachStarted, isFeatureSeen, markFeatureSeen } from './guidedDecisionState';
import './GuidedDecision.css';

const ACCENT = '#a0036c';
const PAD = 6;
const TT_WIDTH = 320;
const MODAL_SELECTORS = [
  '[role="dialog"][aria-modal="true"]',
  '.jas-modal-overlay',
  '.jas-account-modal-overlay',
  '.scores-compare-modal-overlay',
];

// Teachable areas of the workspace. Order = priority. `event` is the
// interaction that counts as "the user has discovered this".
const FEATURES = [
  {
    key: 'chat',
    selector: '.jas-chat-input-area',
    event: 'focusin',
    placement: 'top',
    title: 'Start here.',
    body: "Tell Jaspen what you're working on — type, speak, paste notes, or share a transcript.",
  },
  {
    key: 'objective',
    selector: '.jas-objective-tags',
    event: 'click',
    placement: 'top',
    title: 'Set a primary objective.',
    body: 'Optional — tell Jaspen what to optimize for: Balanced, Cost, Speed, or Growth.',
  },
  {
    key: 'dataContext',
    selector: '.jas-connector-context-tags',
    event: 'click',
    placement: 'top',
    title: 'Add context.',
    body: 'Optional — pull in data from sources like Jira, Salesforce, or Snowflake to enrich your analysis.',
  },
  {
    key: 'guidedDecision',
    selector: '.gd-nav-icon',
    event: 'click',
    placement: 'bottom',
    title: 'Need help framing your thoughts?',
    body: 'Guided Decision helps you organize a complex situation before you begin.',
  },
];

const findVisible = (selector) => {
  const els = Array.from(document.querySelectorAll(selector));
  return els.find((el) => el.offsetParent !== null && el.getBoundingClientRect().width > 0) || null;
};
const hasVisibleModal = () => MODAL_SELECTORS.some((selector) => Boolean(findVisible(selector)));
const clamp = (v, min, max) => Math.max(min, Math.min(v, max));

// Self-managing coach: no props beyond `user`. Decides on its own whether to
// surface anything, never blocks the workspace, and quietly records which
// features the user has discovered.
export default function Walkthrough({ user }) {
  const [queue, setQueue] = useState([]);
  const [idx, setIdx] = useState(0);
  const [rect, setRect] = useState(null);
  const [modalOpen, setModalOpen] = useState(false);
  const dismissed = useRef(false);

  const hasUser = Boolean(user?.id || user?.email);
  const current = queue[idx] || null;

  useEffect(() => {
    const checkModalState = () => setModalOpen(hasVisibleModal());
    checkModalState();
    const observer = new MutationObserver(checkModalState);
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });
    window.addEventListener('resize', checkModalState);
    return () => {
      observer.disconnect();
      window.removeEventListener('resize', checkModalState);
    };
  }, []);

  // Always-on, lightweight discovery tracking: using a feature marks it seen,
  // so it won't be taught later — even if the coach never highlighted it.
  useEffect(() => {
    if (!hasUser) return undefined;
    const cleanups = [];
    const attach = () => {
      FEATURES.forEach((f) => {
        const el = findVisible(f.selector);
        if (!el || el.dataset.gdCoachTracked) return;
        el.dataset.gdCoachTracked = '1';
        const handler = () => markFeatureSeen(user, f.key);
        el.addEventListener(f.event, handler, true);
        cleanups.push(() => el.removeEventListener(f.event, handler, true));
      });
    };
    const t = setTimeout(attach, 400);
    return () => {
      clearTimeout(t);
      cleanups.forEach((fn) => fn());
    };
  }, [hasUser, user]);

  // Build the coach queue once the workspace has painted.
  useEffect(() => {
    if (!hasUser) return undefined;
    const t = setTimeout(() => {
      const firstRun = !getCoachStarted(user);
      const unseen = FEATURES.filter((f) => !isFeatureSeen(user, f.key) && findVisible(f.selector));
      // First login teaches everything unseen; later logins nudge just one.
      const q = firstRun ? unseen : unseen.slice(0, 1);
      setCoachStarted(user);
      if (q.length) {
        setQueue(q);
        setIdx(0);
      }
    }, 700);
    return () => clearTimeout(t);
  }, [hasUser, user]);

  const end = useCallback(() => {
    dismissed.current = true;
    setQueue([]);
  }, []);

  // Advance to the next still-unseen feature in the queue.
  const advance = useCallback(() => {
    setIdx((i) => {
      let n = i + 1;
      while (n < queue.length && isFeatureSeen(user, queue[n].key)) n += 1;
      if (n >= queue.length) {
        dismissed.current = true;
        setQueue([]);
        return i;
      }
      return n;
    });
  }, [queue, user]);

  // While a coachmark is up, interacting with its target advances the coach.
  useEffect(() => {
    if (!current || modalOpen) return undefined;
    const el = findVisible(current.selector);
    if (!el) {
      advance();
      return undefined;
    }
    const onInteract = () => {
      markFeatureSeen(user, current.key);
      advance();
    };
    el.addEventListener(current.event, onInteract, true);
    return () => el.removeEventListener(current.event, onInteract, true);
  }, [current, advance, user, modalOpen]);

  // Track the target's position (reposition on scroll/resize).
  useEffect(() => {
    if (!current || modalOpen) {
      setRect(null);
      return undefined;
    }
    const measure = () => {
      const el = findVisible(current.selector);
      if (el) setRect(el.getBoundingClientRect());
    };
    measure();
    window.addEventListener('resize', measure);
    window.addEventListener('scroll', measure, true);
    return () => {
      window.removeEventListener('resize', measure);
      window.removeEventListener('scroll', measure, true);
    };
  }, [current, modalOpen]);

  if (modalOpen || !current || !rect) return null;

  const next = () => {
    markFeatureSeen(user, current.key);
    advance();
  };
  const skip = () => {
    markFeatureSeen(user, current.key); // acknowledge the one they saw
    end();
  };

  const tipLeft = clamp(
    rect.left + rect.width / 2 - TT_WIDTH / 2,
    12,
    window.innerWidth - TT_WIDTH - 12,
  );
  const tipPos =
    current.placement === 'top'
      ? { left: tipLeft, bottom: window.innerHeight - rect.top + PAD + 12 }
      : { left: tipLeft, top: rect.bottom + PAD + 12 };

  const isLast = idx + 1 >= queue.length;

  return (
    <>
      {/* Highlight ring — visual only, no dimming, no click capture.
          Clamped to the viewport: targets like the composer sit flush against
          the window edge, and an unclamped ring (target + PAD) would draw its
          border offscreen, making the target itself look cut off. */}
      {(() => {
        const ringTop = clamp(rect.top - PAD, 4, window.innerHeight - 8);
        const ringLeft = clamp(rect.left - PAD, 4, window.innerWidth - 8);
        const ringBottom = clamp(rect.bottom + PAD, ringTop + 8, window.innerHeight - 4);
        const ringRight = clamp(rect.right + PAD, ringLeft + 8, window.innerWidth - 4);
        return (
          <div
            className="gd-coach-ring"
            style={{
              position: 'fixed',
              top: ringTop,
              left: ringLeft,
              width: ringRight - ringLeft,
              height: ringBottom - ringTop,
              zIndex: 6000,
            }}
          />
        );
      })()}
      {/* Coachmark */}
      <div style={{ ...tooltip, ...tipPos }}>
        <h3 style={tipTitle}>{current.title}</h3>
        <p style={tipBody}>{current.body}</p>
        <div style={tipFooter}>
          <div style={dots}>
            {queue.map((_, i) => (
              <span
                key={i}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: i === idx ? ACCENT : 'rgba(26,29,36,0.18)',
                }}
              />
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button type="button" style={skipLink} onClick={skip}>
              {isLast ? 'Dismiss' : 'Skip'}
            </button>
            <button type="button" style={primaryBtnSm} onClick={next}>
              {isLast ? 'Got it' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

const FONT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';
const tooltip = {
  position: 'fixed',
  zIndex: 6001,
  width: TT_WIDTH,
  boxSizing: 'border-box',
  background: '#fff',
  borderRadius: 14,
  boxShadow: '0 18px 50px rgba(15,18,25,0.28)',
  padding: '16px 16px 12px',
  color: '#1a1d24',
  fontFamily: FONT,
  pointerEvents: 'auto',
};
const tipTitle = { fontSize: '1rem', fontWeight: 600, margin: '0 0 6px' };
const tipBody = { fontSize: '0.86rem', lineHeight: 1.5, color: 'rgba(26,29,36,0.62)', margin: '0 0 14px' };
const tipFooter = { display: 'flex', alignItems: 'center', justifyContent: 'space-between' };
const dots = { display: 'flex', alignItems: 'center', gap: 6 };
const primaryBtnSm = {
  fontFamily: FONT, fontSize: '0.85rem', fontWeight: 600, padding: '8px 16px',
  borderRadius: 9, border: 'none', cursor: 'pointer', background: ACCENT, color: '#fff',
};
const skipLink = {
  fontFamily: FONT, fontSize: '0.85rem', fontWeight: 500, color: 'rgba(26,29,36,0.55)',
  background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  textDecoration: 'underline', textUnderlineOffset: 3,
};
