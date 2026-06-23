// Inline styles for the modal shell. Inlined (not CSS classes) so the
// production app's global stylesheet cannot override the critical structural
// and visual properties — guarantees a clean, well-padded, high-contrast modal
// regardless of cascade order.

export const ACCENT = '#a0036c';

export const overlay = {
  position: 'fixed',
  inset: 0,
  zIndex: 5000,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
  padding: '24px',
  boxSizing: 'border-box',
  fontFamily:
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif',
};

export const backdrop = {
  position: 'absolute',
  inset: 0,
  background: 'rgba(15, 18, 25, 0.55)',
  backdropFilter: 'blur(3px)',
  WebkitBackdropFilter: 'blur(3px)',
};

const cardBase = {
  position: 'relative',
  background: '#ffffff',
  borderRadius: '20px',
  boxShadow: '0 30px 80px rgba(15, 18, 25, 0.35)',
  width: '100%',
  boxSizing: 'border-box',
  color: '#1a1d24',
  display: 'flex',
  flexDirection: 'column',
};

export const welcomeCard = {
  ...cardBase,
  maxWidth: '460px',
  padding: '40px 40px 32px',
};

export const wizardCard = {
  ...cardBase,
  maxWidth: '720px',
  maxHeight: 'calc(100vh - 48px)',
  overflow: 'hidden',
};

export const welcomeTitle = {
  fontSize: '1.55rem',
  fontWeight: 600,
  lineHeight: 1.2,
  letterSpacing: '-0.01em',
  margin: '0 0 14px',
  color: '#1a1d24',
};

export const welcomeBody = {
  fontSize: '1rem',
  lineHeight: 1.6,
  color: 'rgba(26, 29, 36, 0.62)',
  margin: '0 0 30px',
};

export const welcomeActions = {
  display: 'flex',
  justifyContent: 'flex-end',
  alignItems: 'center',
  gap: '12px',
};

export const btnPrimary = {
  fontSize: '0.95rem',
  fontWeight: 600,
  padding: '11px 22px',
  borderRadius: '11px',
  border: 'none',
  cursor: 'pointer',
  background: ACCENT,
  color: '#ffffff',
};

export const btnGhost = {
  fontSize: '0.95rem',
  fontWeight: 600,
  padding: '11px 18px',
  borderRadius: '11px',
  border: 'none',
  cursor: 'pointer',
  background: 'transparent',
  color: 'rgba(26, 29, 36, 0.55)',
};

export const closeBtn = {
  position: 'absolute',
  top: '16px',
  right: '16px',
  zIndex: 2,
  width: '34px',
  height: '34px',
  border: 'none',
  borderRadius: '9px',
  background: 'transparent',
  color: 'rgba(26, 29, 36, 0.5)',
  cursor: 'pointer',
  fontSize: '16px',
  lineHeight: 1,
};
