import React, { useId } from 'react';
import AssumptionField from '../AssumptionField';
import { REVIEW_ASSUMPTIONS } from '../../config/questions';
import { getBenchmark } from '../../data/benchmarks';
import { formatCurrency } from '../../engine/formatting';

// Step 2 — review the pre-populated benchmark assumptions. The user reviews and
// adjusts anything that differs from their organization rather than filling in a
// blank form.
export default function BenchmarkReviewStep({
  defaults,
  assumptionValue,
  isAssumptionOverridden,
  overrideAssumption,
  restoreAssumption,
  restoreAll,
  overriddenKeys,
  inputs,
  resolvedSalary,
  resolvedSupport,
  setInput,
}) {
  const uid = useId();
  return (
    <section className="cot-card" aria-labelledby={`${uid}-title`}>
      <div className="cot-assumption-head" style={{ marginBottom: 6 }}>
        <h2 id={`${uid}-title`} style={{ margin: 0 }}>
          Review the assumptions
        </h2>
        {overriddenKeys.length > 0 ? (
          <button type="button" className="cot-link" onClick={restoreAll}>
            Restore all recommended defaults
          </button>
        ) : null}
      </div>
      <p className="cot-card-lead">
        We&apos;ve done the research for you. Each value shows whether it is a published benchmark or
        a research-based estimate, along with its source. Review and adjust anything that differs
        from your organization — you don&apos;t need to change a thing to see your result.
      </p>

      {REVIEW_ASSUMPTIONS.map((field) => {
        const meta = defaults[field.key];
        const benchmark = getBenchmark(meta?.benchmarkId);
        return (
          <AssumptionField
            key={field.key}
            field={field}
            benchmark={benchmark}
            value={assumptionValue(field.key)}
            defaultValue={meta?.value}
            overridden={isAssumptionOverridden(field.key)}
            onChange={(v) => {
              if (v === '' || v == null) return;
              overrideAssumption(field.key, v);
            }}
            onRestore={() => restoreAssumption(field.key)}
          />
        );
      })}

      <hr className="cot-divider" />

      {/* Blended support salary — an organization input used for internal labor. */}
      <div className="cot-assumption" data-overridden="false">
        <div className="cot-assumption-head">
          <p className="cot-assumption-title">
            Blended salary for internal support and project time
          </p>
          <span className="cot-badge cot-badge-org">Your Organization&apos;s Inputs</span>
        </div>
        <p className="cot-help">
          Used to value coworker time (onboarding, knowledge transfer, reconstruction, project
          support). Defaults to the role salary.
        </p>
        <div className="cot-assumption-controls">
          <div className="cot-input-affix cot-assumption-input">
            <span className="cot-prefix" aria-hidden="true">$</span>
            <input
              className="cot-input"
              type="number"
              min={0}
              step={1000}
              aria-label="Blended support salary in USD"
              placeholder={String(Math.round(resolvedSalary))}
              value={inputs.blendedSupportSalary ?? ''}
              onChange={(e) =>
                setInput('blendedSupportSalary', e.target.value === '' ? null : Number(e.target.value))
              }
            />
          </div>
          <span className="cot-help" style={{ margin: 0 }}>
            Currently {formatCurrency(resolvedSupport)}
          </span>
        </div>
      </div>
    </section>
  );
}
