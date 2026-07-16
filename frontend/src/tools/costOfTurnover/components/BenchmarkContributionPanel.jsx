import React, { useState } from 'react';
import { analytics } from '../services/analytics';

// Optional, explicit, opt-in (disabled by default) consent to contribute
// anonymized calculator inputs for aggregated benchmark improvement. Separate
// from account creation and from marketing consent. No employee names,
// confidential project names, or unnecessary PII are collected.
export default function BenchmarkContributionPanel() {
  const [consent, setConsent] = useState(false); // disabled by default
  const [recorded, setRecorded] = useState(false);

  const handleChange = (checked) => {
    setConsent(checked);
    setRecorded(true);
    analytics.benchmarkContributionConsent(checked);
  };

  return (
    <section className="cot-panel" aria-labelledby="cot-contrib-title">
      <h3 id="cot-contrib-title">Help improve future benchmarks</h3>
      <p>
        Several defaults in this tool are research-based estimates because no direct benchmark
        exists yet. You can optionally contribute your anonymized, non-identifying inputs (role
        category and level, hours, and cost figures) to help improve these benchmarks over time.
      </p>
      <label className="cot-consent">
        <input type="checkbox" checked={consent} onChange={(e) => handleChange(e.target.checked)} />
        <span>
          Yes, contribute my anonymized inputs to help improve future benchmarks. This is optional,
          separate from creating an account and from marketing, and off by default. We never collect
          employee names, confidential project names, or unnecessary personal information, and we do
          not use your data for benchmark development without this explicit consent.
        </span>
      </label>
      {recorded ? (
        <p className={`cot-status ${consent ? 'cot-status-ok' : ''}`} role="status" style={{ color: consent ? '' : '#8791a6' }}>
          {consent
            ? 'Thank you — your anonymized contribution preference is recorded.'
            : 'Contribution declined. Nothing will be shared.'}
        </p>
      ) : null}
    </section>
  );
}
