import React, { useId } from 'react';
import { ROLE_CATEGORIES, ROLE_LEVELS, INDUSTRIES, COUNTRIES, defaultSalaryFor } from '../../data/roles';
import { formatCurrency } from '../../engine/formatting';

// Step 1 — minimal role setup. Only departures, category, and level are
// required; salary can fall back to the benchmark placeholder.
export default function RoleSetupStep({ inputs, setInput, salaryEdited, useBenchmarkSalary }) {
  const uid = useId();
  const benchSalary = defaultSalaryFor(inputs);

  return (
    <section className="cot-card" aria-labelledby={`${uid}-title`}>
      <h2 id={`${uid}-title`}>About the role</h2>
      <p className="cot-card-lead">
        Tell us just enough to initialize the estimate. Everything else is pre-filled with
        researched defaults you can review and adjust on the next step.
      </p>

      <div className="cot-field-grid">
        <div className="cot-field">
          <label className="cot-label" htmlFor={`${uid}-dep`}>
            How many departures of this type are you modeling?
          </label>
          <input
            id={`${uid}-dep`}
            className="cot-input"
            type="number"
            min={1}
            step={1}
            inputMode="numeric"
            value={inputs.departures}
            onChange={(e) => setInput('departures', Math.max(1, Number(e.target.value) || 1))}
          />
        </div>

        <div className="cot-field">
          <label className="cot-label" htmlFor={`${uid}-cat`}>
            Role category
          </label>
          <select
            id={`${uid}-cat`}
            className="cot-select"
            value={inputs.roleCategory}
            onChange={(e) => setInput('roleCategory', e.target.value)}
          >
            {ROLE_CATEGORIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </div>

        <div className="cot-field">
          <label className="cot-label" htmlFor={`${uid}-lvl`}>
            Role level
          </label>
          <select
            id={`${uid}-lvl`}
            className="cot-select"
            value={inputs.roleLevel}
            onChange={(e) => setInput('roleLevel', e.target.value)}
          >
            {ROLE_LEVELS.map((l) => (
              <option key={l.id} value={l.id}>
                {l.label}
              </option>
            ))}
          </select>
        </div>

        <div className="cot-field">
          <label className="cot-label" htmlFor={`${uid}-sal`}>
            Annual salary
          </label>
          <div className="cot-input-affix">
            <span className="cot-prefix" aria-hidden="true">$</span>
            <input
              id={`${uid}-sal`}
              className="cot-input"
              type="number"
              min={0}
              step={1000}
              inputMode="numeric"
              value={inputs.salary ?? ''}
              onChange={(e) => setInput('salary', e.target.value === '' ? '' : Number(e.target.value))}
            />
          </div>
          {salaryEdited ? (
            <div className="cot-inline-toggle">
              <button type="button" className="cot-chip-toggle" onClick={useBenchmarkSalary}>
                Reset to published benchmark ({formatCurrency(benchSalary)})
              </button>
            </div>
          ) : null}
          <p className="cot-help">
            {salaryEdited
              ? "Using your organization's salary."
              : `Prefilled with the ${formatCurrency(benchSalary)} role benchmark (a directional placeholder pending a BLS OEWS lookup). Edit it to use your organization's figure for an accurate estimate.`}
          </p>
        </div>

        <div className="cot-field">
          <label className="cot-label" htmlFor={`${uid}-ind`}>
            Industry <span className="cot-help" style={{ display: 'inline' }}>(optional)</span>
          </label>
          <select
            id={`${uid}-ind`}
            className="cot-select"
            value={inputs.industry}
            onChange={(e) => setInput('industry', e.target.value)}
          >
            {INDUSTRIES.map((i) => (
              <option key={i.id || 'none'} value={i.id}>
                {i.label}
              </option>
            ))}
          </select>
        </div>

        <div className="cot-field">
          <label className="cot-label" htmlFor={`${uid}-country`}>
            Country
          </label>
          <select
            id={`${uid}-country`}
            className="cot-select"
            value={inputs.country}
            onChange={(e) => setInput('country', e.target.value)}
          >
            {COUNTRIES.map((c) => (
              <option key={c.id} value={c.id}>
                {c.label}
              </option>
            ))}
          </select>
        </div>
      </div>
    </section>
  );
}
