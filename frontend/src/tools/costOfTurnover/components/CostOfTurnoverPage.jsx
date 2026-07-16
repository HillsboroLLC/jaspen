import React, { useEffect, useMemo, useRef, useState } from 'react';
import MarketingPageLayout from '../../../pages/Marketing/MarketingPageLayout';
import Seo from '../../../shared/components/Seo';
import Stepper from './Stepper';
import RoleSetupStep from './steps/RoleSetupStep';
import BenchmarkReviewStep from './steps/BenchmarkReviewStep';
import KnowledgeImpactStep from './steps/KnowledgeImpactStep';
import ResultsStep from './steps/ResultsStep';
import CompositionPanel from './CompositionPanel';
import MethodologyModal from './MethodologyModal';
import { useCostOfTurnover } from '../hooks/useCostOfTurnover';
import { STEPS } from '../config/questions';
import { analytics } from '../services/analytics';
import { buildSnapshot } from '../services/savedEstimate';
import { seoJsonLd, SEO } from '../config/seo';
import '../CostOfTurnover.css';

export default function CostOfTurnoverPage() {
  const cot = useCostOfTurnover();
  const [methodologyOpen, setMethodologyOpen] = useState(false);
  const startedRef = useRef(false);
  const topRef = useRef(null);
  const lastStepRef = useRef(0);

  // utility_view on mount.
  useEffect(() => {
    analytics.utilityViewed();
  }, []);

  // Fire calculator_started once, and step_completed on forward transitions.
  useEffect(() => {
    if (cot.step > 0 && !startedRef.current) {
      startedRef.current = true;
      analytics.calculatorStarted();
    }
    if (cot.step > lastStepRef.current) {
      const prev = STEPS[lastStepRef.current];
      if (prev) analytics.stepCompleted(prev.id, prev.index);
    }
    lastStepRef.current = cot.step;
    // Move focus to the top of the step region for screen-reader users.
    if (topRef.current) topRef.current.focus({ preventScroll: false });
    if (typeof window !== 'undefined') window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [cot.step]);

  const estimateSummary = useMemo(
    () => ({
      utility: 'cost_of_turnover',
      total_low: Math.round(cot.result.total.low),
      total_mid: Math.round(cot.result.total.mid),
      total_high: Math.round(cot.result.total.high),
      built_using: cot.builtUsing,
      role_category: cot.inputs.roleCategory,
      role_level: cot.inputs.roleLevel,
      departures: cot.inputs.departures,
    }),
    [cot.result, cot.builtUsing, cot.inputs]
  );

  const getSnapshot = () =>
    buildSnapshot({
      inputs: cot.inputs,
      overrides: cot.overrides,
      defaults: Object.fromEntries(Object.entries(cot.defaults).map(([k, v]) => [k, v.value])),
      result: cot.result,
      builtUsing: cot.builtUsing,
    });

  const isResults = cot.step === 3;

  return (
    <MarketingPageLayout pageClass="page-tool-cot">
      <Seo
        title={SEO.title}
        description={SEO.description}
        canonicalPath={SEO.canonicalPath}
        type="website"
        jsonLd={seoJsonLd()}
      />
      <div className="cot">
        <div className="cot-shell">
          <span tabIndex={-1} ref={topRef} className="cot-sr-only">
            {STEPS[cot.step].title}
          </span>

          {!isResults && (
            <header className="cot-hero">
              <p className="cot-kicker">Free business utility · No sign-up to start</p>
              <h1>Estimate the True Cost of Employee Turnover</h1>
              <p className="cot-hero-sub">
                Traditional calculators stop at recruiting and vacancy. This one also estimates the
                organizational knowledge and context that leave with a person — using published
                benchmarks and documented research, with every assumption visible and editable.
              </p>
              <ul className="cot-hero-facts">
                <li>Prefilled with researched defaults</li>
                <li>About 2 minutes</li>
                <li>Full results with no email required</li>
              </ul>
            </header>
          )}

          <Stepper current={cot.step} onStepClick={cot.goTo} />

          {isResults ? (
            <>
              <ResultsStep
                result={cot.result}
                builtUsing={cot.builtUsing}
                getSnapshot={getSnapshot}
                estimateSummary={estimateSummary}
                onOpenMethodology={() => setMethodologyOpen(true)}
                onRevise={() => cot.goTo(0)}
              />
              <div className="cot-actions" style={{ justifyContent: 'center', marginTop: 32 }}>
                <button type="button" className="cot-btn cot-btn-ghost" onClick={cot.resetEstimate}>
                  Start a new estimate
                </button>
              </div>
            </>
          ) : (
            /* Full-width two-column layout: the step card keeps its size; the
               live Estimate Composition panel fills the freed space beside it. */
            <div className="cot-layout">
              <div className="cot-main">
                {cot.step === 0 && (
                  <RoleSetupStep
                    inputs={cot.inputs}
                    setInput={cot.setInput}
                    salaryEdited={cot.salaryEdited}
                    useBenchmarkSalary={cot.useBenchmarkSalary}
                  />
                )}
                {cot.step === 1 && (
                  <BenchmarkReviewStep
                    defaults={cot.defaults}
                    assumptionValue={cot.assumptionValue}
                    isAssumptionOverridden={cot.isAssumptionOverridden}
                    overrideAssumption={cot.overrideAssumption}
                    restoreAssumption={cot.restoreAssumption}
                    restoreAll={cot.restoreAll}
                    overriddenKeys={cot.overriddenKeys}
                    inputs={cot.inputs}
                    resolvedSalary={cot.resolvedSalary}
                    resolvedSupport={cot.resolvedSupport}
                    setInput={cot.setInput}
                  />
                )}
                {cot.step === 2 && (
                  <KnowledgeImpactStep
                    inputs={cot.inputs}
                    setInput={cot.setInput}
                    defaults={cot.defaults}
                    assumptionValue={cot.assumptionValue}
                    isAssumptionOverridden={cot.isAssumptionOverridden}
                    overrideAssumption={cot.overrideAssumption}
                    restoreAssumption={cot.restoreAssumption}
                  />
                )}

                <div className="cot-actions">
                  <div className="cot-actions-secondary">
                    {cot.step > 0 ? (
                      <button type="button" className="cot-btn cot-btn-ghost" onClick={cot.back}>
                        ← Back
                      </button>
                    ) : null}
                    {cot.hasEdits ? (
                      <button type="button" className="cot-reset-link" onClick={cot.resetEstimate}>
                        Reset to researched defaults
                      </button>
                    ) : null}
                  </div>
                  <button type="button" className="cot-btn cot-btn-primary" onClick={cot.next}>
                    {cot.step === 2 ? 'See my estimate' : 'Continue'} →
                  </button>
                </div>
              </div>

              <div className="cot-insights">
                <CompositionPanel builtUsing={cot.builtUsing} />
              </div>
            </div>
          )}
        </div>
      </div>

      <MethodologyModal open={methodologyOpen} onClose={() => setMethodologyOpen(false)} />
    </MarketingPageLayout>
  );
}
