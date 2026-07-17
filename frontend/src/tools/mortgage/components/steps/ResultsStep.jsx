import React, { useEffect } from 'react';
import { formatCurrency, formatCurrencyCompact, formatPercent } from '../../../shared/formatting';
import CompositionPanel from '../../../shared/components/CompositionPanel';
import WhyChanged from '../../../shared/components/WhyChanged';
import SaveEstimatePanel from '../../../shared/components/SaveEstimatePanel';
import JaspenCta from '../../../shared/components/JaspenCta';
import { analytics, UTILITY_SOURCE } from '../../services/analytics';

function Line({ label, sub, value, strong }) {
  return (
    <div className="tool-line">
      <span>
        <span className="tool-line-label" style={strong ? { fontWeight: 800 } : undefined}>{label}</span>
        {sub ? <span className="tool-line-sub">{sub}</span> : null}
      </span>
      <span className="tool-line-value">{value}</span>
    </div>
  );
}

export default function ResultsStep({ result, composition, whyChanged, getSnapshot, estimateSummary, onOpenMethodology, onRevise }) {
  useEffect(() => {
    analytics.calculatorCompleted({ true_monthly: Math.round(result.tiers.trueCarrying) });
    analytics.resultsViewed({ true_monthly: Math.round(result.tiers.trueCarrying) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const m = result.monthly;
  const byYear = result.horizons.reduce((a, h) => ({ ...a, [h.years]: h }), {});

  return (
    <div>
      {/* Dual hero */}
      <div className="tool-result-hero">
        <div className="tool-result-heroes">
          <div>
            <p className="tool-kicker">True monthly carrying cost</p>
            <div className="tool-result-figure">
              {formatCurrencyCompact(result.tiers.trueCarrying)}
              <small>{formatCurrency(result.tiers.trueCarrying)} / month</small>
            </div>
            <p className="tool-result-range">
              Range <strong>{formatCurrency(result.trueMonthly.low)}</strong>–<strong>{formatCurrency(result.trueMonthly.high)}</strong>
            </p>
          </div>
          <div>
            <p className="tool-kicker">Cash needed to close</p>
            <div className="tool-result-figure">
              {formatCurrencyCompact(result.cashToClose.mid)}
              <small>upfront</small>
            </div>
            <p className="tool-result-range">
              Range <strong>{formatCurrency(result.cashToClose.low)}</strong>–<strong>{formatCurrency(result.cashToClose.high)}</strong>
            </p>
          </div>
        </div>
        <p className="tool-result-disclaimer">
          An evidence-based estimate, not a lender quote, approval, or prediction. It does not tell
          you whether to buy. Confirm figures with your lender Loan Estimate and financial partners.
        </p>
      </div>

      {/* Three tiers: required lender payment vs true cost */}
      <section className="tool-card" aria-labelledby="tiers-title">
        <h2 id="tiers-title">Required payment vs. true cost</h2>
        <p className="tool-card-lead">The lender only requires part of what a home actually costs each month.</p>
        <div className="tool-tiers">
          <div className="tool-tier">
            <h3>Principal &amp; interest</h3>
            <div className="tool-tier-value">{formatCurrency(result.tiers.pi)}</div>
            <p className="tool-tier-note">The loan payment only</p>
          </div>
          <div className="tool-tier">
            <h3>Required housing payment</h3>
            <div className="tool-tier-value">{formatCurrency(result.tiers.requiredPayment)}</div>
            <p className="tool-tier-note">P&amp;I + taxes + insurance + PMI + HOA</p>
          </div>
          <div className="tool-tier" style={{ borderColor: 'var(--tool-primary)' }}>
            <h3>True carrying cost</h3>
            <div className="tool-tier-value">{formatCurrency(result.tiers.trueCarrying)}</div>
            <p className="tool-tier-note">+ maintenance reserve + utilities</p>
          </div>
        </div>
      </section>

      {/* Monthly breakdown */}
      <section className="tool-card" aria-labelledby="breakdown-title">
        <div className="tool-assumption-head" style={{ marginBottom: 4 }}>
          <h2 id="breakdown-title" style={{ margin: 0 }}>Monthly cost breakdown</h2>
          <button type="button" className="tool-link" onClick={onRevise}>Revise an input</button>
        </div>
        <Line label="Principal & interest" value={formatCurrency(m.pi)} />
        <Line label="Property tax" value={formatCurrency(m.tax)} />
        <Line label="Homeowners insurance" value={formatCurrency(m.insurance)} />
        {m.pmi > 0 ? <Line label="PMI" sub="Until the modeled removal point" value={formatCurrency(m.pmi)} /> : null}
        {m.hoa > 0 ? <Line label="HOA" value={formatCurrency(m.hoa)} /> : null}
        <Line label="Required housing payment" value={formatCurrency(result.tiers.requiredPayment)} strong />
        <Line label="Maintenance reserve" sub="Planning amount, not a required bill" value={formatCurrency(m.maintenance)} />
        {m.utilities > 0 ? <Line label="Utilities" value={formatCurrency(m.utilities)} /> : null}
        <Line label="True carrying cost" value={formatCurrency(result.tiers.trueCarrying)} strong />
      </section>

      {/* Top drivers */}
      <section className="tool-card" aria-labelledby="drivers-title">
        <h2 id="drivers-title">Your three largest cost drivers</h2>
        <p className="tool-card-lead">Where your monthly housing cost concentrates.</p>
        <div className="tool-drivers">
          {result.topDrivers.map((d, i) => (
            <div className="tool-driver" key={d.key}>
              <span className="tool-driver-rank">#{i + 1}</span>
              <p className="tool-driver-name">{d.label}</p>
              <div className="tool-driver-value">{formatCurrency(d.value)}</div>
              <p className="tool-tier-note">{formatPercent((d.value / result.tiers.trueCarrying) * 100)} of true cost</p>
            </div>
          ))}
        </div>
      </section>

      {/* Multi-year cost */}
      <section className="tool-card" aria-labelledby="horizon-title">
        <h2 id="horizon-title">Multi-year cost of ownership</h2>
        <p className="tool-card-lead">
          Total cash out, equity built, and interest paid — shown at today&apos;s costs (see
          payment-change exposure below for how costs can grow).
        </p>
        <div className="tool-scroll-x">
          <table className="tool-table">
            <thead>
              <tr>
                <th>Horizon</th>
                <th>Total cash out</th>
                <th>Interest paid</th>
                <th>Equity built</th>
                <th>Net cost after equity</th>
              </tr>
            </thead>
            <tbody>
              {[1, 3, 5, 10].map((y) => (
                <tr key={y}>
                  <td>{y} {y === 1 ? 'year' : 'years'}</td>
                  <td>{formatCurrency(byYear[y].totalOutflow)}</td>
                  <td>{formatCurrency(byYear[y].interestPaid)}</td>
                  <td>{formatCurrency(byYear[y].equityBuilt)}</td>
                  <td>{formatCurrency(byYear[y].netCostAfterEquity)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="tool-insights-note" style={{ borderTop: 0, paddingTop: 8 }}>
          Equity built includes your down payment plus principal paid, and excludes any home-price
          appreciation. It is kept separate from cost, never subtracted from your monthly payment.
        </p>
      </section>

      {/* Payment-change exposure */}
      <section className="tool-card" aria-labelledby="exposure-title">
        <h2 id="exposure-title">Payment-change exposure</h2>
        <p className="tool-card-lead">
          A fixed-rate loan does not mean a fixed housing cost. Taxes, insurance, HOA, and
          maintenance can still rise. These are editable scenarios, not forecasts.
        </p>
        {result.exposure.map((e) => (
          <Line
            key={e.years}
            label={`Projected true monthly in ${e.years} years`}
            sub={`+${formatCurrency(e.increaseVsToday)} vs. today`}
            value={formatCurrency(e.projectedTrueMonthly)}
          />
        ))}
      </section>

      {/* Housing ratio */}
      {result.ratios.true != null ? (
        <section className="tool-card" aria-labelledby="ratio-title">
          <h2 id="ratio-title">Housing-cost ratio</h2>
          <p className="tool-card-lead">
            Share of gross income used for housing. Context only (HUD flags 30% as cost-burdened,
            50% as severely burdened) — never an approval decision.
          </p>
          <Line label="Required payment ratio" value={formatPercent(result.ratios.required * 100, 1)} />
          <Line label="True carrying cost ratio" value={formatPercent(result.ratios.true * 100, 1)} strong />
        </section>
      ) : null}

      {/* Why changed */}
      {whyChanged.length > 0 ? (
        <section className="tool-card">
          <WhyChanged items={whyChanged} unitLabel="true monthly cost" onView={() => analytics.whyChangedViewed()} />
        </section>
      ) : null}

      {/* Composition */}
      <section className="tool-card">
        <CompositionPanel composition={composition} variant="card" />
      </section>

      {/* Methodology */}
      <section className="tool-card" aria-labelledby="method-title">
        <h2 id="method-title">How we built these estimates</h2>
        <p className="tool-card-lead">
          Published benchmarks where they exist (Freddie Mac rate, CFPB/HUD definitions), documented
          research-based estimates otherwise. Every assumption is visible and editable; the result is
          an estimate, not a lender quote.
        </p>
        <button type="button" className="tool-btn tool-btn-ghost" onClick={() => { analytics.methodologyViewed(); onOpenMethodology(); }}>
          View full methodology and sources
        </button>
      </section>

      <div style={{ marginTop: 20 }}>
        <JaspenCta
          kicker="Beyond the number"
          title="Two homes rarely compare on the sticker price"
          intro="You now have the true cost of this home. The harder question is which option is actually better once cash to close, carrying cost, equity, and payment growth are all on the table."
          bullets={[
            'Compare multiple mortgage options',
            'Save this calculation',
            'Track changes over time',
            'Pressure-test different assumptions',
            'Use these numbers inside Jaspen',
            'Explore rent vs. buy later',
          ]}
          closing="Jaspen can hold each scenario, its assumptions, and the reasoning behind your choice — so a decision this large stays explainable months from now."
          ctaLabel="Take these numbers into Jaspen"
          ctaTo="/"
          onCta={() => analytics.jaspenCtaClicked('home')}
        />
      </div>

      <div style={{ marginTop: 20 }}>
        <SaveEstimatePanel utilityType="mortgage" source={UTILITY_SOURCE} getSnapshot={getSnapshot} estimateSummary={estimateSummary} analytics={analytics} />
      </div>
    </div>
  );
}
