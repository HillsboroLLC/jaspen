import React, { useId } from 'react';
import AssumptionField from '../AssumptionField';
import { KNOWLEDGE_FIELDS, isFieldVisible } from '../../config/questions';
import { getBenchmark, CONTEXT_STATS } from '../../data/benchmarks';

// Step 3 — knowledge and context. Conditional questions keep the path short:
// transfer hours hide for unplanned exits; project-disruption hours hide until
// at least one project is affected.
export default function KnowledgeImpactStep({
  inputs,
  setInput,
  defaults,
  assumptionValue,
  isAssumptionOverridden,
  overrideAssumption,
  restoreAssumption,
}) {
  const uid = useId();
  const state = inputs;

  return (
    <section className="cot-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>Knowledge and context</h2>
      <p className="cot-card-lead">
        These are the costs traditional calculators leave out. About {Math.round(CONTEXT_STATS.uniqueKnowledge.value * 100)}% of a
        role&apos;s institutional knowledge is unique to the person who holds it (Panopto, 2018) — a
        few quick questions size what a departure puts at risk.
      </p>

      {KNOWLEDGE_FIELDS.map((field) => {
        if (!isFieldVisible(field, state)) return null;

        if (field.kind === 'choice') {
          return (
            <fieldset key={field.key} className="cot-field" style={{ border: 0, padding: 0, margin: '0 0 22px' }}>
              <legend className="cot-label">{field.label}</legend>
              <div className="cot-choices" role="radiogroup" aria-label={field.label}>
                {field.options.map((opt) => {
                  const selected = (state[field.key] ?? field.default) === opt.id;
                  return (
                    <label key={opt.id} className="cot-choice" data-selected={selected ? 'true' : 'false'}>
                      <input
                        type="radio"
                        name={field.key}
                        value={opt.id}
                        checked={selected}
                        onChange={() => setInput(field.key, opt.id)}
                      />
                      {opt.label}
                    </label>
                  );
                })}
              </div>
            </fieldset>
          );
        }

        if (field.kind === 'number') {
          return (
            <div key={field.key} className="cot-field">
              <label className="cot-label" htmlFor={`${uid}-${field.key}`}>
                {field.label}
              </label>
              <div className="cot-input-affix" style={{ maxWidth: 220 }}>
                <input
                  id={`${uid}-${field.key}`}
                  className="cot-input"
                  type="number"
                  min={field.min ?? 0}
                  step={field.step || 1}
                  inputMode="numeric"
                  value={state[field.key] ?? field.default ?? 0}
                  onChange={(e) => setInput(field.key, Math.max(0, Number(e.target.value) || 0))}
                />
                {field.unit ? <span className="cot-input-suffix">{field.unit}</span> : null}
              </div>
            </div>
          );
        }

        // assumption (hours) — editable benchmark with provenance + source
        const meta = defaults[field.key];
        return (
          <AssumptionField
            key={field.key}
            field={{ ...field, kind: 'number', step: 1 }}
            benchmark={getBenchmark(meta?.benchmarkId)}
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
    </section>
  );
}
