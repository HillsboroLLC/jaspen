import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Building2, ShieldCheck, FileText } from 'lucide-react';
import MarketingPageLayout from '../../../pages/Marketing/MarketingPageLayout';
import Seo from '../../../shared/components/Seo';
import CalculatorSeoFooter from '../../../shared/components/CalculatorSeoFooter';
import Stepper from '../../shared/components/Stepper';
import CompositionPanel from '../../shared/components/CompositionPanel';
import MethodologyModal from '../../shared/components/MethodologyModal';
import LeaseBasicsStep from './steps/LeaseBasicsStep';
import RecurringStep from './steps/RecurringStep';
import MoveInStep from './steps/MoveInStep';
import ResultsStep from './steps/ResultsStep';
import { useRent } from '../hooks/useRent';
import { STEPS } from '../config/questions';
import { SEO, seoJsonLd, FAQS } from '../config/seo';
import { BENCHMARKS, METHODOLOGY_VERSION, BENCHMARK_VERSION } from '../data/benchmarks';
import { analytics } from '../services/analytics';
import { CALC_VERSION } from '../engine/version';
import '../../shared/tools-shared.css';

const METHOD_BENCHMARKS = Object.values(BENCHMARKS).map((b) => ({
  ...b,
  displayValue: b.displayValue || (b.id === 'R006' ? "1 month's rent" : b.value != null ? `${(b.value * 100).toFixed(1)}%` : 'Future'),
}));
const METHOD_PRINCIPLES = [
  { title: 'Lease facts lead', body: 'advertised rent, concessions, recurring charges, deposits, and move-in fees come from you and your lease.' },
  { title: 'Cash is not always cost', body: 'refundable deposits are shown as cash held, never silently counted as rental expense.' },
  { title: 'Defaults reduce friction', body: 'a deposit fallback and editable growth scenarios fill gaps without pretending to know your property.' },
  { title: 'Deterministic and transparent', body: 'the calculator uses fixed formulas, no AI, and never makes a rent or affordability recommendation.' },
];
const METHOD_NOTES = [
  'Free-rent concessions are applied once to the initial lease term.',
  'Prepaid rent changes move-in cash timing but is not added again as an extra cost.',
  'Effective Monthly Cost spreads nonrefundable move-in costs across the lease term.',
  'Local market-rent comparison remains a future enhancement; an optional ZIP does not change v1 results.',
];

export default function RentCalculatorPage() {
  const rent = useRent();
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const startedRef = useRef(false);
  const lastStepRef = useRef(0);
  const topRef = useRef(null);
  useEffect(() => { analytics.utilityViewed(); }, []);
  useEffect(() => {
    if (rent.step > 0 && !startedRef.current) { startedRef.current = true; analytics.calculatorStarted(); }
    if (rent.step > lastStepRef.current) { const prev = STEPS[lastStepRef.current]; if (prev) analytics.stepCompleted(prev.id, prev.index); }
    lastStepRef.current = rent.step;
    if (topRef.current) topRef.current.focus({ preventScroll: false });
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [rent.step]);

  const estimateSummary = useMemo(() => ({ utility: 'rent', advertised_rent: Math.round(rent.result.advertisedRent), effective_monthly: Math.round(rent.result.effectiveMonthlyCost), move_in_cash: Math.round(rent.result.moveInCashRequired), composition: rent.composition }), [rent.result, rent.composition]);
  const getSnapshot = () => ({
    utility_type: 'rent', source: 'rent_calculator_utility', calculator_version: CALC_VERSION, benchmark_version: BENCHMARK_VERSION,
    user_inputs: rent.inputs, overrides: rent.overrides,
    defaults_used: Object.fromEntries(Object.entries(rent.defaults).map(([k, v]) => [k, v.value])),
    result_breakdown: { effectiveMonthlyCost: rent.result.effectiveMonthlyCost, moveInCashRequired: rent.result.moveInCashRequired, horizons: rent.result.horizons },
    total_low: Math.round(rent.result.advertisedRent), total_mid: Math.round(rent.result.effectiveMonthlyCost), total_high: Math.round(rent.result.moveInCashRequired), built_using: rent.composition, updated_date: new Date().toISOString(),
  });
  const isResults = rent.step === 3;

  return <MarketingPageLayout pageClass="page-tool-rent">
    <Seo title={SEO.title} description={SEO.description} canonicalPath={SEO.canonicalPath} type="website" jsonLd={seoJsonLd()} />
    <div className="tool tool--rent"><div className="tool-shell">
      <span tabIndex={-1} ref={topRef} className="tool-sr-only">{STEPS[rent.step].title}</span>
      {!isResults && <header className="tool-hero"><p className="tool-kicker"><Building2 size={16} aria-hidden="true" /> Free · No sign-up to start</p><h1>The true cost of renting this home</h1><p className="tool-hero-sub">Go beyond advertised rent. See concessions, recurring fees, utilities, insurance, move-in cash, renewal exposure, and multi-year cost — with every assumption visible and editable.</p><ul className="tool-hero-facts"><li><ShieldCheck size={16} aria-hidden="true" /> Deterministic math, no AI</li><li><FileText size={16} aria-hidden="true" /> Prefilled, editable assumptions</li><li><Building2 size={16} aria-hidden="true" /> Full results, no email required</li></ul></header>}
      <Stepper steps={STEPS} current={rent.step} onStepClick={rent.goTo} />
      {isResults ? <><ResultsStep result={rent.result} composition={rent.composition} whyChanged={rent.whyChanged} getSnapshot={getSnapshot} estimateSummary={estimateSummary} onOpenMethodology={() => setMethodologyOpen(true)} onRevise={() => rent.goTo(0)} /><div className="tool-actions" style={{ justifyContent: 'center', marginTop: 32 }}><button type="button" className="tool-btn tool-btn-ghost" onClick={rent.resetEstimate}>Start a new calculation</button></div></> :
        <div className="tool-layout"><div className="tool-main">
          {rent.step === 0 && <LeaseBasicsStep inputs={rent.inputs} setInput={rent.setInput} result={rent.result} />}
          {rent.step === 1 && <RecurringStep inputs={rent.inputs} setInput={rent.setInput} result={rent.result} />}
          {rent.step === 2 && <MoveInStep inputs={rent.inputs} setInput={rent.setInput} defaults={rent.defaults} assumptionValue={rent.assumptionValue} isAssumptionOverridden={rent.isAssumptionOverridden} overrideAssumption={rent.overrideAssumption} restoreAssumption={rent.restoreAssumption} result={rent.result} />}
          <div className="tool-reset-row"><button type="button" className="tool-reset-link" onClick={rent.resetEstimate}>Reset to researched defaults</button></div>
          <div className="tool-actions">{rent.step > 0 ? <button type="button" className="tool-btn tool-btn-ghost" onClick={rent.back}>← Back</button> : <span />}<button type="button" className="tool-btn tool-btn-primary" onClick={rent.next}>{rent.step === 2 ? 'See my true cost' : 'Continue'} →</button></div>
        </div><div className="tool-insights"><CompositionPanel composition={rent.composition} /></div></div>}
    </div></div>
    <CalculatorSeoFooter
      faqs={FAQS}
      intro={(
        <>
          <p>This calculator turns a lease into its real numbers: the advertised rent, the effective rent after any free month or credit, the recurring fees and utilities you pay each month, and the cash you need to move in. It separates money you spend from refundable deposits you get back, and shows how the cost changes if the rent rises at renewal.</p>
          <p>Every input starts from a researched default and stays fully editable, the math is deterministic (no AI), and it never tells you whether to rent or buy.</p>
        </>
      )}
    />
    <MethodologyModal open={methodologyOpen} onClose={() => setMethodologyOpen(false)} title="How We Built These Rent Estimates" versionLine={`Methodology v${METHODOLOGY_VERSION} · Benchmark library v${BENCHMARK_VERSION}. An estimation tool, not a lease quote or recommendation.`} principles={METHOD_PRINCIPLES} benchmarks={METHOD_BENCHMARKS} notes={METHOD_NOTES} />
  </MarketingPageLayout>;
}
