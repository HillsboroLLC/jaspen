import React from 'react';
import { isLeadsMockEnabled, leadsMockMode } from '../../shared/lead/leadClient';
import './LeadsMockNotice.css';

// Dev-only banner shown inside a lead-capture form when the lead API is being
// mocked, so it is always obvious that no real submission is happening. Renders
// nothing when the mock is off (and can never render in a production build,
// since leadsMockMode() is hard-gated on NODE_ENV). Intentionally uses warning
// (amber) styling, not brand colors, so it reads as a development artifact.
export default function LeadsMockNotice() {
  if (!isLeadsMockEnabled()) return null;
  const mode = leadsMockMode();
  const modeLabel = mode === 'fail' ? 'FAIL (simulated error)' : 'SUCCESS';

  return (
    <div className="leads-mock-notice" role="status">
      <span className="lmn-dot" aria-hidden="true" />
      <span className="lmn-text">
        <strong>Dev mock mode:</strong> lead submissions are simulated
        (<code>{modeLabel}</code>). Nothing is sent to the real API.
        <span className="lmn-hint"> Toggle with <code>?leadsMock=success|fail|off</code>.</span>
      </span>
    </div>
  );
}
