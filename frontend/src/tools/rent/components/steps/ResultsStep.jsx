import React, { useEffect } from 'react';
import { formatCurrency, formatCurrencyCompact, formatPercent } from '../../../shared/formatting';
import CompositionPanel from '../../../shared/components/CompositionPanel';
import WhyChanged from '../../../shared/components/WhyChanged';
import SaveEstimatePanel from '../../../shared/components/SaveEstimatePanel';
import JaspenCta from '../../../shared/components/JaspenCta';
import { analytics, UTILITY_SOURCE } from '../../services/analytics';

function Line({ label, sub, value, strong }) {
  return <div className="tool-line"><span><span className="tool-line-label" style={strong ? { fontWeight: 800 } : undefined}>{label}</span>{sub ? <span className="tool-line-sub">{sub}</span> : null}</span><span className="tool-line-value">{value}</span></div>;
}

export default function ResultsStep({ result, composition, whyChanged, getSnapshot, estimateSummary, onOpenMethodology, onRevise }) {
  useEffect(() => {
    analytics.calculatorCompleted({ effective_monthly: Math.round(result.effectiveMonthlyCost) });
    analytics.resultsViewed({ effective_monthly: Math.round(result.effectiveMonthlyCost) });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const m = result.monthlyBreakdown;
  return (
    <div>
      <div className="tool-result-hero">
        <div className="tool-result-heroes">
          <div><p className="tool-kicker">Effective monthly cost</p><div className="tool-result-figure">{formatCurrencyCompact(result.effectiveMonthlyCost)}<small>{formatCurrency(result.effectiveMonthlyCost)} / month</small></div><p className="tool-result-range">Recurring costs plus nonrefundable move-in costs spread across this lease.</p></div>
          <div><p className="tool-kicker">Cash needed to move in</p><div className="tool-result-figure">{formatCurrencyCompact(result.moveInCashRequired)}<small>{formatCurrency(result.refundableCashHeld)} is refundable cash held</small></div></div>
        </div>
        <p className="tool-result-disclaimer">A transparent planning estimate, not a lease quote or affordability recommendation. Confirm all amounts and refund terms in the lease.</p>
      </div>

      <section className="tool-card"><h2>From advertised rent to true cost</h2><p className="tool-card-lead">Concessions are counted once. Refundable deposits remain cash held, not cost.</p><div className="tool-tiers tool-tiers--four">
        <div className="tool-tier"><h3>Advertised rent</h3><div className="tool-tier-value">{formatCurrency(result.advertisedRent)}</div><p className="tool-tier-note">The listing price</p></div>
        <div className="tool-tier"><h3>Effective first-year rent</h3><div className="tool-tier-value">{formatCurrency(result.effectiveFirstYearRent)}</div><p className="tool-tier-note">After the initial concession</p></div>
        <div className="tool-tier"><h3>True monthly rent cost</h3><div className="tool-tier-value">{formatCurrency(result.trueMonthlyRentCost)}</div><p className="tool-tier-note">+ recurring fees, utilities &amp; insurance</p></div>
        <div className="tool-tier" style={{ borderColor: 'var(--tool-primary)' }}><h3>Effective Monthly Cost</h3><div className="tool-tier-value">{formatCurrency(result.effectiveMonthlyCost)}</div><p className="tool-tier-note">+ amortized nonrefundable move-in costs</p></div>
      </div></section>

      <section className="tool-card"><div className="tool-assumption-head"><h2 style={{ margin: 0 }}>Monthly breakdown</h2><button type="button" className="tool-link" onClick={onRevise}>Revise an input</button></div>
        <Line label="Effective rent" value={formatCurrency(m.effectiveRent)} /><Line label="Parking" value={formatCurrency(m.parking)} /><Line label="Pet rent" value={formatCurrency(m.petRent)} /><Line label="Other recurring fees" value={formatCurrency(m.otherFees)} /><Line label="Renter's insurance" value={formatCurrency(m.insurance)} /><Line label="Utilities" value={formatCurrency(m.utilities)} /><Line label="True monthly rent cost" value={formatCurrency(result.trueMonthlyRentCost)} strong />
      </section>

      <section className="tool-card"><h2>Move-in cash</h2><p className="tool-card-lead">Cash timing and actual cost are deliberately kept separate.</p><Line label="Refundable cash held" sub="Security and pet deposits" value={formatCurrency(result.refundableCashHeld)} /><Line label="Nonrefundable move-in cost" value={formatCurrency(result.nonrefundableMoveInCost)} /><Line label="Total cash required at move-in" value={formatCurrency(result.moveInCashRequired)} strong /></section>

      <section className="tool-card"><h2>Multi-year rental cost</h2><p className="tool-card-lead">Concessions apply only to the first lease term; future rent and recurring costs use your editable growth assumptions.</p><div className="tool-scroll-x"><table className="tool-table"><thead><tr><th>Horizon</th><th>Total cash paid</th><th>Net cost</th><th>Average monthly</th><th>Ending rent</th></tr></thead><tbody>{result.horizons.map((h) => <tr key={h.years}><td>{h.years} {h.years === 1 ? 'year' : 'years'}</td><td>{formatCurrency(h.totalCashPaid)}</td><td>{formatCurrency(h.netCostExclRefundable)}</td><td>{formatCurrency(h.avgMonthlyCost)}</td><td>{formatCurrency(h.endingMonthlyRent)}</td></tr>)}</tbody></table></div></section>

      <section className="tool-card"><h2>Renewal exposure</h2><p className="tool-card-lead">Low, current, and high rent-growth scenarios show how your monthly cost could change; they are not forecasts.</p><div className="tool-scroll-x"><table className="tool-table"><thead><tr><th>Renewal year</th><th>Low (2%)</th><th>Your assumption</th><th>High (5%)</th></tr></thead><tbody>{result.renewal.map((r) => <tr key={r.year}><td>Year {r.year}</td><td>{formatCurrency(r.low)}</td><td>{formatCurrency(r.mid)}</td><td>{formatCurrency(r.high)}</td></tr>)}</tbody></table></div></section>

      {result.topHiddenCosts.length ? <section className="tool-card"><h2>Your largest costs beyond rent</h2><div className="tool-drivers">{result.topHiddenCosts.map((d, i) => <div className="tool-driver" key={d.key}><span className="tool-driver-rank">#{i + 1}</span><p className="tool-driver-name">{d.label}</p><div className="tool-driver-value">{formatCurrency(d.value)}</div><p className="tool-tier-note">per month</p></div>)}</div></section> : null}
      {result.housingRatio != null ? <section className="tool-card"><h2>Housing-cost ratio</h2><p className="tool-card-lead">HUD context only: above 30% of gross income is considered cost-burdened and above 50% severely burdened. This is not personalized advice.</p><Line label="True monthly rent cost / gross income" value={formatPercent(result.housingRatio * 100, 1)} strong /></section> : null}
      {whyChanged.length ? <section className="tool-card"><WhyChanged items={whyChanged} unitLabel="3-year rental cost" onView={() => analytics.whyChangedViewed()} /></section> : null}
      <section className="tool-card"><CompositionPanel composition={composition} variant="card" /></section>
      <section className="tool-card"><h2>How we built these estimates</h2><p className="tool-card-lead">Your lease facts drive the result. Published HUD thresholds provide context, while transparent research estimates fill only the assumptions you have not replaced.</p><button type="button" className="tool-btn tool-btn-ghost" onClick={() => { analytics.methodologyViewed(); onOpenMethodology(); }}>View full methodology and sources</button></section>
      <div style={{ marginTop: 20 }}><JaspenCta kicker="Beyond the number" title="Compare the lease, not just the rent" intro="Keep each rental scenario, its assumptions, and the reasoning behind your choice together in Jaspen." bullets={['Compare multiple rental options', 'Save this calculation', 'Pressure-test concessions and renewals', 'Keep decision context with the numbers']} closing="The calculator gives you the cost. Jaspen helps you make and preserve the decision." ctaLabel="Take these numbers into Jaspen" ctaTo="/" onCta={() => analytics.jaspenCtaClicked('home')} /></div>
      <div style={{ marginTop: 20 }}><SaveEstimatePanel utilityType="rent" source={UTILITY_SOURCE} getSnapshot={getSnapshot} estimateSummary={estimateSummary} analytics={analytics} /></div>
    </div>
  );
}
