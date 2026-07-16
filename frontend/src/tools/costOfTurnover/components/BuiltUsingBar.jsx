import React, { useEffect } from 'react';
import { analytics } from '../services/analytics';

// "Estimate Built Using" — a form-wide 3-way composition that always totals
// 100%. This is composition, not accuracy. Values are available as text (not
// color alone) for accessibility.
const SEGMENTS = [
  {
    key: 'published',
    label: 'Published Benchmarks',
    cls: 'cot-bu-published',
    def: 'Values directly measured and published by authoritative sources for the same or closely matching variable.',
  },
  {
    key: 'research',
    label: 'Research-Based Estimates',
    cls: 'cot-bu-research',
    def: 'Values Jaspen derives through documented methodology using credible published research when no direct benchmark exists for the exact variable.',
  },
  {
    key: 'org',
    label: "Your Organization's Inputs",
    cls: 'cot-bu-org',
    def: 'Values you supplied or modified.',
  },
];

export default function BuiltUsingBar({ builtUsing }) {
  useEffect(() => {
    analytics.compositionViewed();
  }, []);

  return (
    <section className="cot-card" aria-labelledby="cot-builtusing-title">
      <h2 id="cot-builtusing-title">Estimate Composition</h2>
      <p className="cot-card-lead">
        How this estimate was constructed across published benchmarks, research-based estimates, and
        your own inputs. This is a composition of the estimate — not an accuracy, confidence, or
        quality score.
      </p>

      <div className="cot-builtusing-bar" role="img" aria-label={
        `Estimate composition: Published Benchmarks ${builtUsing.published}%, ` +
        `Research-Based Estimates ${builtUsing.research}%, Your Organization's Inputs ${builtUsing.org}%.`
      }>
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

      <div className="cot-bu-legend">
        {SEGMENTS.map((seg) => (
          <div className="cot-bu-legend-item" key={seg.key}>
            <strong>
              <span className={`cot-bu-legend-dot ${seg.cls}`} aria-hidden="true" />
              {seg.label}: {builtUsing[seg.key]}%
            </strong>
            {seg.def}
          </div>
        ))}
      </div>

      <p className="cot-note">
        A larger research-based share means &quot;more derived,&quot; never &quot;more correct.&quot;
        Enter more of your organization&apos;s own figures to shift the composition toward your
        inputs.
      </p>
    </section>
  );
}
