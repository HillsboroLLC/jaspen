import React from 'react';

// Live "Estimate Composition" insights panel shown beside the steps. Updates
// dynamically as the user fills in or overrides values. Transparency only —
// this is what the estimate is built FROM, never a confidence, quality,
// precision, accuracy, or reliability score.
const SEGMENTS = [
  {
    key: 'published',
    label: 'Published Benchmarks',
    cls: 'cot-bu-published',
    def: 'Values directly measured and published by authoritative organizations for the same or closely matching variable.',
  },
  {
    key: 'research',
    label: 'Research-Based Estimates',
    cls: 'cot-bu-research',
    def: 'Values Jaspen derives through documented methodology using multiple credible published sources where no direct benchmark exists.',
  },
  {
    key: 'org',
    label: "Your Organization's Inputs",
    cls: 'cot-bu-org',
    def: 'Values you entered or modified that personalize the estimate.',
  },
];

export default function CompositionPanel({ builtUsing }) {
  return (
    <aside className="cot-insights-panel" aria-labelledby="cot-comp-panel-title">
      <p className="cot-insights-eyebrow">Transparency</p>
      <h3 id="cot-comp-panel-title">Estimate Composition</h3>
      <p className="cot-insights-lead">
        What your estimate is built from. Updates live as you review and personalize it.
      </p>

      <div
        className="cot-builtusing-bar cot-builtusing-bar--slim"
        role="img"
        aria-label={
          `Estimate composition: Published Benchmarks ${builtUsing.published}%, ` +
          `Research-Based Estimates ${builtUsing.research}%, Your Organization's Inputs ${builtUsing.org}%.`
        }
      >
        {SEGMENTS.map((seg) =>
          builtUsing[seg.key] > 0 ? (
            <div
              key={seg.key}
              className={`cot-bu-seg ${seg.cls}${builtUsing[seg.key] < 10 ? ' cot-bu-seg--compact' : ''}`}
              style={{ flexBasis: `${builtUsing[seg.key]}%` }}
            >
              {builtUsing[seg.key]}%
            </div>
          ) : null
        )}
      </div>

      <ul className="cot-insights-legend">
        {SEGMENTS.map((seg) => (
          <li key={seg.key}>
            <span className="cot-insights-legend-row">
              <span className={`cot-bu-legend-dot ${seg.cls}`} aria-hidden="true" />
              <span className="cot-insights-legend-label">{seg.label}</span>
              <span className="cot-insights-legend-pct">{builtUsing[seg.key]}%</span>
            </span>
            <span className="cot-insights-legend-def">{seg.def}</span>
          </li>
        ))}
      </ul>

      <p className="cot-insights-note">
        This shows how the estimate was constructed — not its accuracy, confidence, or quality.
        Entering your own numbers shifts the mix toward your inputs.
      </p>
    </aside>
  );
}
