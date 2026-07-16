// =====================================================
// Cost of Turnover — flow state hook
// Owns input state, benchmark overrides, and step navigation; derives the
// engine result and the Estimate Composition. Presentation components read from
// here and never compute costs themselves.
//
// Salary is PREPOPULATED with the role benchmark as a real, visible number
// (not a placeholder). We track whether the user has edited it away from the
// benchmark: an unedited salary is treated as a benchmark value in the
// composition; once edited it becomes one of "Your Organization's Inputs".
// =====================================================

import { useCallback, useMemo, useState } from 'react';
import { calculate, getDefaultAssumptions } from '../engine/calculator';
import { computeBuiltUsing } from '../engine/builtUsing';
import { defaultSalaryFor } from '../data/roles';
import { ROLE_FIELDS } from '../config/questions';
import { analytics } from '../services/analytics';

const initialRole = {
  roleCategory: ROLE_FIELDS.roleCategory.default,
  roleLevel: ROLE_FIELDS.roleLevel.default,
};

const initialInputs = () => ({
  departures: ROLE_FIELDS.departures.default,
  roleCategory: initialRole.roleCategory,
  roleLevel: initialRole.roleLevel,
  // Prepopulated with the benchmark salary as a real number.
  salary: defaultSalaryFor(initialRole),
  industry: ROLE_FIELDS.industry.default,
  country: ROLE_FIELDS.country.default,
  blendedSupportSalary: null,
  knowledgeTransferPlanned: 'partial',
  affectedProjects: 0,
});

export function useCostOfTurnover() {
  const [step, setStep] = useState(0);
  const [inputs, setInputs] = useState(initialInputs);
  const [overrides, setOverrides] = useState({});
  const [editedInputs, setEditedInputs] = useState(() => new Set());
  // Has the user changed the salary away from the role benchmark?
  const [salaryEdited, setSalaryEdited] = useState(false);

  const salaryProvided = salaryEdited;
  const salaryDefault = useMemo(() => defaultSalaryFor(inputs), [inputs]);
  const resolvedSalary = Number(inputs.salary) || salaryDefault;
  const supportProvided =
    inputs.blendedSupportSalary != null && String(inputs.blendedSupportSalary).trim() !== '';
  const resolvedSupport = supportProvided ? Number(inputs.blendedSupportSalary) : resolvedSalary;

  const defaults = useMemo(() => getDefaultAssumptions(inputs), [inputs]);

  const resolvedAssumptions = useMemo(() => {
    const out = {};
    Object.keys(defaults).forEach((key) => {
      const overridden = Object.prototype.hasOwnProperty.call(overrides, key);
      out[key] = { value: overridden ? Number(overrides[key]) : defaults[key].value };
    });
    return out;
  }, [defaults, overrides]);

  const engineInputs = useMemo(
    () => ({
      departures: inputs.departures,
      salary: resolvedSalary,
      blendedSupportSalary: resolvedSupport,
      affectedProjects: inputs.affectedProjects,
      knowledgeTransferPlanned: inputs.knowledgeTransferPlanned,
    }),
    [inputs.departures, inputs.affectedProjects, inputs.knowledgeTransferPlanned, resolvedSalary, resolvedSupport]
  );

  const result = useMemo(
    () => calculate(engineInputs, resolvedAssumptions),
    [engineInputs, resolvedAssumptions]
  );

  const overriddenKeys = useMemo(() => Object.keys(overrides), [overrides]);

  const builtUsing = useMemo(
    () => computeBuiltUsing(defaults, overriddenKeys, editedInputs),
    [defaults, overriddenKeys, editedInputs]
  );

  const setInput = useCallback((key, value) => {
    setEditedInputs((previous) => {
      const next = new Set(previous);
      next.add(key);
      return next;
    });
    setInputs((prev) => {
      const next = { ...prev, [key]: value };
      // Keep the salary prepopulated with the role benchmark until the user
      // edits it themselves.
      if (key === 'salary') {
        setSalaryEdited(true);
      } else if (key === 'roleCategory' || key === 'roleLevel') {
        setSalaryEdited((edited) => {
          if (!edited) {
            next.salary = defaultSalaryFor({
              roleCategory: next.roleCategory,
              roleLevel: next.roleLevel,
            });
          }
          return edited;
        });
      }
      return next;
    });
  }, []);

  // "Use published benchmark" — reset salary to the role benchmark default.
  const useBenchmarkSalary = useCallback(() => {
    setInputs((prev) => ({
      ...prev,
      salary: defaultSalaryFor({ roleCategory: prev.roleCategory, roleLevel: prev.roleLevel }),
    }));
    setSalaryEdited(false);
    setEditedInputs((previous) => {
      const next = new Set(previous);
      next.delete('salary');
      return next;
    });
  }, []);

  const overrideAssumption = useCallback(
    (key, value) => {
      setOverrides((prev) => ({ ...prev, [key]: value }));
      analytics.benchmarkOverridden(key, defaults[key]?.benchmarkId);
    },
    [defaults]
  );

  const restoreAssumption = useCallback((key) => {
    setOverrides((prev) => {
      if (!Object.prototype.hasOwnProperty.call(prev, key)) return prev;
      const next = { ...prev };
      delete next[key];
      return next;
    });
    analytics.benchmarkRestored(key);
  }, []);

  const restoreAll = useCallback(() => setOverrides({}), []);

  const resetEstimate = useCallback(() => {
    setInputs(initialInputs());
    setOverrides({});
    setEditedInputs(new Set());
    setSalaryEdited(false);
    setStep(0);
  }, []);

  const hasEdits = editedInputs.size > 0 || overriddenKeys.length > 0;

  const isAssumptionOverridden = useCallback(
    (key) => Object.prototype.hasOwnProperty.call(overrides, key),
    [overrides]
  );

  const assumptionValue = useCallback(
    (key) => (Object.prototype.hasOwnProperty.call(overrides, key) ? Number(overrides[key]) : defaults[key]?.value),
    [overrides, defaults]
  );

  const goTo = useCallback((index) => setStep(index), []);
  const next = useCallback(() => setStep((s) => Math.min(s + 1, 3)), []);
  const back = useCallback(() => setStep((s) => Math.max(s - 1, 0)), []);

  return {
    // state
    step,
    inputs,
    overrides,
    overriddenKeys,
    salaryProvided,
    salaryEdited,
    salaryDefault,
    resolvedSalary,
    resolvedSupport,
    defaults,
    result,
    builtUsing,
    hasEdits,
    // actions
    setInput,
    useBenchmarkSalary,
    overrideAssumption,
    restoreAssumption,
    restoreAll,
    resetEstimate,
    isAssumptionOverridden,
    assumptionValue,
    goTo,
    next,
    back,
  };
}
