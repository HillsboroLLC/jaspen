import React, { useEffect } from 'react';
import { CATEGORY } from '../../engine/calculator';
import { formatCurrency, formatCurrencyCompact, formatPercent } from '../../engine/formatting';
import BuiltUsingBar from '../BuiltUsingBar';
import SaveEstimatePanel from '../SaveEstimatePanel';
import BenchmarkContributionPanel from '../BenchmarkContributionPanel';
import JaspenCta from '../JaspenCta';
import { analytics } from '../../services/analytics';

function ComponentRow({ c }) {
  return (
    <article className="cot-comp" data-cat={c.category}>
      <div className="cot-comp-head">
        <h4 className="cot-comp-name">{c.label}</h4>
        <span className="cot-comp-value">{formatCurrency(c.mid)}</span>
      </div>
      <div className="cot-comp-bar" aria-hidden="true">
        <span style={{ width: `${Math.min(100, c.pctOfTotal)}%` }} />
      </div>
      <div className="cot-comp-meta">
        <span>{formatPercent(c.pctOfTotal, 0)} of midpoint total</span>
        <span>
          Range {formatCurrency(c.low)} – {formatCurrency(c.high)}
        </span>
      </div>
      <p className="cot-comp-explain">{c.explanation}</p>
      <p className="cot-comp-driver">Key driver: {c.driverNote}</p>
    </article>
  );
}

export default function ResultsStep({
  result,
  builtUsing,
  getSnapshot,
  estimateSummary,
  onOpenMethodology,
  onRevise,
}) {
  useEffect(() => {
    analytics.calculatorCompleted({
      total_mid: Math.round(result.total.mid),
    });
    analytics.resultsViewed({ total_mid: Math.round(result.total.mid) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const traditional = result.components.filter((c) => c.category === CATEGORY.TRADITIONAL);
  const knowledge = result.components.filter((c) => c.category === CATEGORY.KNOWLEDGE);
  const totalMid = result.total.mid || 1;
  const tradPct = (result.subtotals.traditional.mid / totalMid) * 100;
  const knowPct = (result.subtotals.knowledge.mid / totalMid) * 100;

  return (
    <div>
      {/* Hero total */}
      <section className="cot-result-hero" aria-labelledby="cot-total-title">
        <p className="cot-kicker">Estimated total cost</p>
        <h2 id="cot-total-title" className="cot-sr-only">
          Estimated total cost of turnover
        </h2>
        <div className="cot-result-figure">{formatCurrencyCompact(result.total.mid)}</div>
        <p className="cot-result-range">
          Evidence-based range{' '}
          <strong>{formatCurrency(result.total.low)}</strong> to{' '}
          <strong>{formatCurrency(result.total.high)}</strong>, midpoint{' '}
          <strong>{formatCurrency(result.total.mid)}</strong>
        </p>
        <p className="cot-result-disclaimer">
          This is an evidence-based estimate, not a prediction or a guaranteed outcome. It models the
          cost for {result.inputs.departures} departure{result.inputs.departures === 1 ? '' : 's'} in
          the selected role. Validate material figures with your HR and Finance partners.
        </p>
      </section>

      {/* Subtotals */}
      <div className="cot-subtotals">
        <section className="cot-card cot-subtotal-card">
          <h3>Traditional turnover costs</h3>
          <div className="cot-subtotal-value">{formatCurrency(result.subtotals.traditional.mid)}</div>
          <p className="cot-subtotal-pct">{formatPercent(tradPct)} of midpoint total</p>
        </section>
        <section className="cot-card cot-subtotal-card">
          <h3>Knowledge and context costs</h3>
          <div className="cot-subtotal-value">{formatCurrency(result.subtotals.knowledge.mid)}</div>
          <p className="cot-subtotal-pct">{formatPercent(knowPct)} of midpoint total</p>
        </section>
      </div>

      {/* Top drivers */}
      <section className="cot-card" aria-labelledby="cot-drivers-title">
        <h2 id="cot-drivers-title">Your three largest cost drivers</h2>
        <p className="cot-card-lead">Where to focus attention first.</p>
        <div className="cot-drivers">
          {result.topDrivers.map((d, i) => (
            <div className="cot-driver" key={d.key}>
              <span className="cot-driver-rank">#{i + 1}</span>
              <p className="cot-driver-name">{d.label}</p>
              <div className="cot-driver-value">{formatCurrency(d.mid)}</div>
              <p className="cot-subtotal-pct">{formatPercent(d.pctOfTotal)} of total</p>
            </div>
          ))}
        </div>
      </section>

      {/* Full breakdown */}
      <section className="cot-card" aria-labelledby="cot-breakdown-title">
        <div className="cot-assumption-head" style={{ marginBottom: 4 }}>
          <h2 id="cot-breakdown-title" style={{ margin: 0 }}>
            Full breakdown
          </h2>
          <button type="button" className="cot-link" onClick={onRevise}>
            Revise an input and recalculate
          </button>
        </div>

        <p className="cot-group-title">Traditional turnover costs</p>
        <div className="cot-breakdown">
          {traditional.map((c) => (
            <ComponentRow key={c.key} c={c} />
          ))}
        </div>

        <p className="cot-group-title">Knowledge and context costs</p>
        <div className="cot-breakdown">
          {knowledge.map((c) => (
            <ComponentRow key={c.key} c={c} />
          ))}
        </div>
      </section>

      {/* Built Using composition */}
      <BuiltUsingBar builtUsing={builtUsing} />

      {/* Methodology + trust */}
      <section className="cot-card" aria-labelledby="cot-method-cta">
        <h2 id="cot-method-cta">How we built these estimates</h2>
        <p className="cot-card-lead">
          Standard turnover costs use published benchmarks where they exist; knowledge and context
          costs use documented research-based estimates where no direct benchmark exists. Every
          assumption is visible and editable, and the result is an estimate, not a prediction.
        </p>
        <button
          type="button"
          className="cot-btn cot-btn-ghost"
          onClick={() => {
            analytics.methodologyViewed();
            onOpenMethodology();
          }}
        >
          View full methodology and sources
        </button>
      </section>

      {/* Jaspen connection — only after value delivered */}
      <div style={{ marginTop: 20 }}>
        <JaspenCta />
      </div>

      {/* Optional save + contribution */}
      <div style={{ marginTop: 20 }}>
        <SaveEstimatePanel getSnapshot={getSnapshot} estimateSummary={estimateSummary} />
      </div>
      <div style={{ marginTop: 20 }}>
        <BenchmarkContributionPanel />
      </div>
    </div>
  );
}
