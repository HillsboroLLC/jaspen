import React from 'react';

// Live "Estimate Composition" — what the estimate is built FROM. Updates as the
// user fills in or overrides values. Transparency only: never a confidence,
// accuracy, precision, quality, or reliability score. Always totals 100%.
const SEGMENTS = [
  {
    key: 'published',
    label: 'Published Benchmarks',
    cls: 'tool-comp-published',
    def: 'Values directly measured and published by authoritative organizations for the same or closely matching variable.',
  },
  {
    key: 'research',
    label: 'Research-Based Estimates',
    cls: 'tool-comp-research',
    def: 'Values Jaspen derives through documented methodology using credible published sources where no direct benchmark exists.',
  },
  {
    key: 'org',
    label: 'Your Inputs',
    cls: 'tool-comp-org',
    def: 'Values you entered or modified that personalize the estimate.',
  },
];

export default function CompositionPanel({ composition, variant = 'panel' }) {
  const slim = variant === 'panel';
  return (
    <aside className="tool-insights-panel" aria-labelledby="tool-comp-title">
      <p className="tool-insights-eyebrow">Transparency</p>
      <h3 id="tool-comp-title">Estimate Composition</h3>
      <p className="tool-insights-lead">
        What your estimate is built from. Updates live as you review and personalize it.
      </p>

      <div
        className={`tool-comp-bar${slim ? ' tool-comp-bar--slim' : ''}`}
        role="img"
        aria-label={
          `Estimate composition: Published Benchmarks ${composition.published}%, ` +
          `Research-Based Estimates ${composition.research}%, Your Inputs ${composition.org}%.`
        }
      >
        {SEGMENTS.map((seg) =>
          composition[seg.key] > 0 ? (
            <div
              key={seg.key}
              className={`tool-comp-seg ${seg.cls}${composition[seg.key] < 10 ? ' tool-comp-seg--compact' : ''}`}
              style={{ flexBasis: `${composition[seg.key]}%` }}
            >
              {composition[seg.key]}%
            </div>
          ) : null
        )}
      </div>

      <ul className="tool-insights-legend">
        {SEGMENTS.map((seg) => (
          <li key={seg.key}>
            <span className="tool-insights-legend-row">
              <span className={`tool-comp-legend-dot ${seg.cls}`} aria-hidden="true" />
              <span className="tool-insights-legend-label">{seg.label}</span>
              <span className="tool-insights-legend-pct">{composition[seg.key]}%</span>
            </span>
            <span className="tool-insights-legend-def">{seg.def}</span>
          </li>
        ))}
      </ul>

      <p className="tool-insights-note">
        This shows how the estimate was constructed — not its accuracy, confidence, or quality.
        Entering your own numbers shifts the mix toward your inputs.
      </p>
    </aside>
  );
}
