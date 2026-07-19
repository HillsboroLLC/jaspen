import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Home, ShieldCheck, FileText } from 'lucide-react';
import MarketingPageLayout from '../../../pages/Marketing/MarketingPageLayout';
import Seo from '../../../shared/components/Seo';
import CalculatorSeoFooter from '../../../shared/components/CalculatorSeoFooter';
import Stepper from '../../shared/components/Stepper';
import CompositionPanel from '../../shared/components/CompositionPanel';
import MethodologyModal from '../../shared/components/MethodologyModal';
import PropertyLoanStep from './steps/PropertyLoanStep';
import AssumptionsStep from './steps/AssumptionsStep';
import CashStep from './steps/CashStep';
import ResultsStep from './steps/ResultsStep';
import { useMortgage } from '../hooks/useMortgage';
import { STEPS } from '../config/questions';
import { SEO, seoJsonLd, FAQS } from '../config/seo';
import { BENCHMARKS, METHODOLOGY_VERSION, BENCHMARK_VERSION } from '../data/benchmarks';
import { analytics } from '../services/analytics';
import { CALC_VERSION } from '../engine/version';
import '../../shared/tools-shared.css';

const METHOD_BENCHMARKS = Object.values(BENCHMARKS).map((b) => ({
  ...b,
  displayValue: `${(b.value * 100).toFixed(b.value < 0.1 ? 2 : 0)}%`,
}));

const METHOD_PRINCIPLES = [
  { title: 'Published benchmarks where they exist', body: 'the current Freddie Mac PMMS rate, and CFPB / HUD definitions and thresholds.' },
  { title: 'Research-based estimates otherwise', body: 'transparent planning ranges for taxes, insurance, PMI, maintenance, and closing costs when no property-specific value exists.' },
  { title: 'Your inputs always win', body: 'a lender quote, tax record, insurance quote, or HOA statement overrides any default.' },
  { title: 'No recommendation, no AI', body: 'deterministic formulas only. The calculator shows cost, cash, equity, and sensitivity — it never tells you whether to buy.' },
];

const METHOD_NOTES = [
  'Multi-year costs are shown at today’s levels; the payment-change exposure view models growth separately.',
  'Equity built excludes home-price appreciation and is never subtracted from monthly cost.',
  'PMI is modeled to stop at the editable removal point (default 80% LTV of the original price); actual removal depends on loan type and lender.',
  'Property tax and homeowners insurance defaults are percentages of home value — a proxy. Local tax data and a real insurance quote are more accurate.',
];

export default function MortgageCalculatorPage() {
  const mtg = useMortgage();
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const startedRef = useRef(false);
  const lastStepRef = useRef(0);
  const topRef = useRef(null);

  useEffect(() => { analytics.utilityViewed(); }, []);

  useEffect(() => {
    if (mtg.step > 0 && !startedRef.current) { startedRef.current = true; analytics.calculatorStarted(); }
    if (mtg.step > lastStepRef.current) {
      const prev = STEPS[lastStepRef.current];
      if (prev) analytics.stepCompleted(prev.id, prev.index);
    }
    lastStepRef.current = mtg.step;
    if (topRef.current) topRef.current.focus({ preventScroll: false });
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [mtg.step]);

  const estimateSummary = useMemo(() => ({
    utility: 'mortgage',
    true_monthly: Math.round(mtg.result.tiers.trueCarrying),
    required_payment: Math.round(mtg.result.tiers.requiredPayment),
    cash_to_close: Math.round(mtg.result.cashToClose.mid),
    home_price: mtg.result.inputs.homePrice,
    composition: mtg.composition,
  }), [mtg.result, mtg.composition]);

  const getSnapshot = () => ({
    utility_type: 'mortgage',
    source: 'mortgage_calculator_utility',
    calculator_version: CALC_VERSION,
    benchmark_version: BENCHMARK_VERSION,
    user_inputs: mtg.inputs,
    overrides: mtg.overrides,
    defaults_used: Object.fromEntries(Object.entries(mtg.defaults).map(([k, v]) => [k, v.value])),
    result_breakdown: {
      tiers: mtg.result.tiers,
      cashToClose: mtg.result.cashToClose.mid,
      horizons: mtg.result.horizons,
    },
    total_low: Math.round(mtg.result.trueMonthly.low),
    total_mid: Math.round(mtg.result.tiers.trueCarrying),
    total_high: Math.round(mtg.result.trueMonthly.high),
    built_using: mtg.composition,
    updated_date: new Date().toISOString(),
  });

  const isResults = mtg.step === 3;

  return (
    <MarketingPageLayout pageClass="page-tool-mortgage">
      <Seo title={SEO.title} description={SEO.description} canonicalPath={SEO.canonicalPath} type="website" jsonLd={seoJsonLd()} />
      <div className="tool tool--mortgage">
        <div className="tool-shell">
          <span tabIndex={-1} ref={topRef} className="tool-sr-only">{STEPS[mtg.step].title}</span>

          {!isResults && (
            <header className="tool-hero">
              <p className="tool-kicker"><Home size={16} strokeWidth={2.25} aria-hidden="true" /> Free · No sign-up to start</p>
              <h1>The true cost of owning this home</h1>
              <p className="tool-hero-sub">
                Most calculators stop at principal and interest. This one shows the required lender
                payment, the true monthly carrying cost, cash to close, equity built, and how costs
                grow over time — with every assumption sourced and editable.
              </p>
              <ul className="tool-hero-facts">
                <li><ShieldCheck size={16} aria-hidden="true" /> Deterministic math, no AI</li>
                <li><FileText size={16} aria-hidden="true" /> Every default sourced &amp; editable</li>
                <li><Home size={16} aria-hidden="true" /> Full results, no email required</li>
              </ul>
            </header>
          )}

          <Stepper steps={STEPS} current={mtg.step} onStepClick={mtg.goTo} />

          {isResults ? (
            <>
              <ResultsStep
                result={mtg.result}
                composition={mtg.composition}
                whyChanged={mtg.whyChanged}
                getSnapshot={getSnapshot}
                estimateSummary={estimateSummary}
                onOpenMethodology={() => setMethodologyOpen(true)}
                onRevise={() => mtg.goTo(0)}
              />
              <div className="tool-actions" style={{ justifyContent: 'center', marginTop: 32 }}>
                <button type="button" className="tool-btn tool-btn-ghost" onClick={mtg.resetEstimate}>Start a new calculation</button>
              </div>
            </>
          ) : (
            <div className="tool-layout">
              <div className="tool-main">
                {mtg.step === 0 && (
                  <PropertyLoanStep
                    inputs={mtg.inputs}
                    setInput={mtg.setInput}
                    assumptionValue={mtg.assumptionValue}
                    overrideAssumption={mtg.overrideAssumption}
                    restoreAssumption={mtg.restoreAssumption}
                    isAssumptionOverridden={mtg.isAssumptionOverridden}
                  />
                )}
                {mtg.step === 1 && (
                  <AssumptionsStep
                    defaults={mtg.defaults}
                    assumptionValue={mtg.assumptionValue}
                    isAssumptionOverridden={mtg.isAssumptionOverridden}
                    overrideAssumption={mtg.overrideAssumption}
                    restoreAssumption={mtg.restoreAssumption}
                    restoreAll={mtg.restoreAll}
                    overriddenKeys={mtg.overriddenKeys}
                    inputs={mtg.inputs}
                    setInput={mtg.setInput}
                  />
                )}
                {mtg.step === 2 && (
                  <CashStep
                    defaults={mtg.defaults}
                    assumptionValue={mtg.assumptionValue}
                    isAssumptionOverridden={mtg.isAssumptionOverridden}
                    overrideAssumption={mtg.overrideAssumption}
                    restoreAssumption={mtg.restoreAssumption}
                    inputs={mtg.inputs}
                    setInput={mtg.setInput}
                    result={mtg.result}
                  />
                )}
                <div className="tool-reset-row">
                  <button type="button" className="tool-reset-link" onClick={mtg.resetEstimate}>Reset to researched defaults</button>
                </div>
                <div className="tool-actions">
                  {mtg.step > 0 ? (
                    <button type="button" className="tool-btn tool-btn-ghost" onClick={mtg.back}>← Back</button>
                  ) : <span />}
                  <button type="button" className="tool-btn tool-btn-primary" onClick={mtg.next}>
                    {mtg.step === 2 ? 'See my true cost' : 'Continue'} →
                  </button>
                </div>
              </div>
              <div className="tool-insights">
                <CompositionPanel composition={mtg.composition} />
              </div>
            </div>
          )}
        </div>
      </div>

      <CalculatorSeoFooter faqs={FAQS} />

      <MethodologyModal
        open={methodologyOpen}
        onClose={() => setMethodologyOpen(false)}
        title="How We Built These Mortgage Estimates"
        versionLine={`Methodology v${METHODOLOGY_VERSION} · Benchmark library v${BENCHMARK_VERSION}. An estimation tool, not a lender quote, approval, or prediction.`}
        principles={METHOD_PRINCIPLES}
        benchmarks={METHOD_BENCHMARKS}
        notes={METHOD_NOTES}
      />
    </MarketingPageLayout>
  );
}
