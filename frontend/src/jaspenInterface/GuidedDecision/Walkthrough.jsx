import React, { useCallback, useEffect, useLayoutEffect, useState } from 'react';

const ACCENT = '#a0036c';
const PAD = 6;
const TT_WIDTH = 340;

// Each step highlights a real section of the workspace. Selectors are resolved
// to the first VISIBLE match so the tour follows what the user actually sees.
const STEPS = [
  {
    selector: '.jas-chat-input-area',
    placement: 'top',
    title: 'Start here.',
    body: "Tell Jaspen what you're working on. Type, speak, paste notes, or share a transcript.",
  },
  {
    selector: '.jas-objective-tags',
    placement: 'top',
    title: 'Optional: Set a primary objective.',
    body: 'This helps Jaspen understand what to optimize for. Examples include Balanced, Cost Optimization, Speed to Market, and Growth.',
  },
  {
    selector: '.jas-connector-context-tags',
    placement: 'top',
    title: 'Optional: Connect additional context.',
    body: 'Data sources like Jira, Salesforce, and Snowflake can help enrich your analysis.',
  },
  {
    selector: '.gd-nav-icon',
    placement: 'bottom',
    title: 'Need help framing your thoughts?',
    body: "Guided Decision helps organize complex situations before you begin. Use this if you're unsure where to start.",
  },
];

const findVisible = (selector) => {
  const els = Array.from(document.querySelectorAll(selector));
  return els.find((el) => el.offsetParent !== null && el.getBoundingClientRect().width > 0) || null;
};

const clamp = (v, min, max) => Math.max(min, Math.min(v, max));

export default function Walkthrough({ open, onClose }) {
  // phase: 'intro' → spotlight steps → 'final'
  const [phase, setPhase] = useState('intro');
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState(null);

  const step = phase === 'steps' ? STEPS[index] : null;

  // Resolve the current target's position; skip steps whose element is absent.
  const measure = useCallback(() => {
    if (!step) return;
    const el = findVisible(step.selector);
    if (!el) {
      // Element not present (e.g. no connected data sources) — skip it.
      setIndex((i) => i + 1);
      return;
    }
    el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    setRect(el.getBoundingClientRect());
  }, [step]);

  useLayoutEffect(() => {
    if (phase !== 'steps') return undefined;
    if (index >= STEPS.length) {
      setPhase('final');
      return undefined;
    }
    measure();
    const onMove = () => {
      const el = findVisible(STEPS[index]?.selector);
      if (el) setRect(el.getBoundingClientRect());
    };
    window.addEventListener('resize', onMove);
    window.addEventListener('scroll', onMove, true);
    return () => {
      window.removeEventListener('resize', onMove);
      window.removeEventListener('scroll', onMove, true);
    };
  }, [phase, index, measure]);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  const next = () => {
    if (index + 1 >= STEPS.length) setPhase('final');
    else setIndex((i) => i + 1);
  };

  // ── Intro / final centered cards ──────────────────────────────────────────
  if (phase === 'intro' || phase === 'final') {
    const isFinal = phase === 'final';
    return (
      <div style={dimBackdrop}>
        <div style={centerCard}>
          <div style={eyebrow}>
            <SparkleGlyph />
            {isFinal ? 'All set' : 'Quick tour'}
          </div>
          <h2 style={cardTitle}>
            {isFinal ? "You're ready." : 'Want a quick look around?'}
          </h2>
          <p style={cardBody}>
            {isFinal
              ? 'Start naturally and Jaspen will help transform complexity into a clear path forward.'
              : "We'll point out a few things in about 20 seconds — or jump straight in if you'd rather get to business."}
          </p>
          <div style={cardActions}>
            {!isFinal && (
              <button type="button" style={ghostBtn} onClick={onClose}>
                Skip the tour
              </button>
            )}
            <button
              type="button"
              style={primaryBtn}
              onClick={isFinal ? onClose : () => setPhase('steps')}
            >
              {isFinal ? 'Got it' : 'Show me around'}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // ── Spotlight step ─────────────────────────────────────────────────────────
  if (!rect) return null;

  const tipLeft = clamp(
    rect.left + rect.width / 2 - TT_WIDTH / 2,
    12,
    window.innerWidth - TT_WIDTH - 12,
  );
  const tipPos =
    step.placement === 'top'
      ? { left: tipLeft, bottom: window.innerHeight - rect.top + PAD + 12 }
      : { left: tipLeft, top: rect.bottom + PAD + 12 };

  return (
    <>
      {/* Dimming + highlight ring (visual only; workspace stays interactive) */}
      <div
        style={{
          position: 'fixed',
          top: rect.top - PAD,
          left: rect.left - PAD,
          width: rect.width + PAD * 2,
          height: rect.height + PAD * 2,
          borderRadius: 12,
          boxShadow: '0 0 0 9999px rgba(15, 18, 25, 0.55)',
          border: `2px solid ${ACCENT}`,
          pointerEvents: 'none',
          zIndex: 6000,
          transition: 'all 0.25s ease',
        }}
      />
      {/* Tooltip */}
      <div style={{ ...tooltip, ...tipPos }}>
        <h3 style={tipTitle}>{step.title}</h3>
        <p style={tipBody}>{step.body}</p>
        <div style={tipFooter}>
          <div style={dots}>
            {STEPS.map((_, i) => (
              <span
                key={i}
                style={{
                  width: 6,
                  height: 6,
                  borderRadius: '50%',
                  background: i === index ? ACCENT : 'rgba(26,29,36,0.18)',
                }}
              />
            ))}
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <button type="button" style={skipLink} onClick={onClose}>
              Skip
            </button>
            <button type="button" style={primaryBtnSm} onClick={next}>
              {index + 1 >= STEPS.length ? 'Finish' : 'Next'}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}

function SparkleGlyph() {
  return (
    <svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M12 2.5l1.6 4.3a4 4 0 0 0 2.36 2.36L20.26 10.75l-4.3 1.6a4 4 0 0 0-2.36 2.36L12 19l-1.6-4.3a4 4 0 0 0-2.36-2.36L3.74 10.75l4.3-1.6a4 4 0 0 0 2.36-2.36L12 2.5z" />
    </svg>
  );
}

// ── Inline styles (isolated from host CSS) ───────────────────────────────────
const FONT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif';

const dimBackdrop = {
  position: 'fixed',
  inset: 0,
  zIndex: 6000,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  background: 'rgba(15, 18, 25, 0.5)',
  backdropFilter: 'blur(2px)',
  WebkitBackdropFilter: 'blur(2px)',
  padding: 24,
  fontFamily: FONT,
};

const centerCard = {
  background: '#fff',
  borderRadius: 20,
  boxShadow: '0 30px 80px rgba(15,18,25,0.35)',
  width: '100%',
  maxWidth: 420,
  padding: '34px 34px 28px',
  color: '#1a1d24',
  boxSizing: 'border-box',
};

const eyebrow = {
  display: 'inline-flex',
  alignItems: 'center',
  gap: 7,
  fontSize: '0.7rem',
  fontWeight: 600,
  letterSpacing: '0.12em',
  textTransform: 'uppercase',
  color: ACCENT,
  marginBottom: 14,
};

const cardTitle = { fontSize: '1.45rem', fontWeight: 600, margin: '0 0 12px', letterSpacing: '-0.01em' };
const cardBody = { fontSize: '0.98rem', lineHeight: 1.6, color: 'rgba(26,29,36,0.62)', margin: '0 0 26px' };
const cardActions = { display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12 };

const tooltip = {
  position: 'fixed',
  zIndex: 6001,
  width: TT_WIDTH,
  boxSizing: 'border-box',
  background: '#fff',
  borderRadius: 14,
  boxShadow: '0 18px 50px rgba(15,18,25,0.3)',
  padding: '18px 18px 14px',
  color: '#1a1d24',
  fontFamily: FONT,
  pointerEvents: 'auto',
};
const tipTitle = { fontSize: '1.02rem', fontWeight: 600, margin: '0 0 6px' };
const tipBody = { fontSize: '0.88rem', lineHeight: 1.5, color: 'rgba(26,29,36,0.62)', margin: '0 0 14px' };
const tipFooter = { display: 'flex', alignItems: 'center', justifyContent: 'space-between' };
const dots = { display: 'flex', alignItems: 'center', gap: 6 };

const primaryBtn = {
  fontFamily: FONT, fontSize: '0.95rem', fontWeight: 600, padding: '11px 22px',
  borderRadius: 11, border: 'none', cursor: 'pointer', background: ACCENT, color: '#fff',
};
const primaryBtnSm = { ...primaryBtn, fontSize: '0.85rem', padding: '8px 16px', borderRadius: 9 };
const ghostBtn = {
  fontFamily: FONT, fontSize: '0.95rem', fontWeight: 600, padding: '11px 18px',
  borderRadius: 11, border: 'none', cursor: 'pointer', background: 'transparent',
  color: 'rgba(26,29,36,0.55)',
};
const skipLink = {
  fontFamily: FONT, fontSize: '0.85rem', fontWeight: 500, color: 'rgba(26,29,36,0.55)',
  background: 'none', border: 'none', padding: 0, cursor: 'pointer',
  textDecoration: 'underline', textUnderlineOffset: 3,
};
