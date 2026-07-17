// =====================================================
// Mortgage calculator — flow state hook.
// Owns inputs, benchmark overrides, edited-input tracking, and step navigation;
// derives the engine result, Estimate Composition, and the "Why your estimate
// changed" explanations.
// =====================================================

import { useCallback, useMemo, useState } from 'react';
import { calculate } from '../engine/calculator';
import { getDefaultAssumptions, DIRECT_INPUTS } from '../data/benchmarks';
import { computeComposition } from '../../shared/composition';
import { formatRate } from '../../shared/formatting';
import { ASSUMPTION_LABELS } from '../config/questions';
import { analytics } from '../services/analytics';

// Assumptions that move the monthly true carrying cost (drive "Why changed").
const MONTHLY_KEYS = new Set(['interestRate', 'propertyTaxRate', 'insuranceRate', 'pmiRate', 'maintenanceRate']);

const initialInputs = () => ({
  homePrice: 400000,
  downPaymentPct: 0.2,
  loanTerm: 30,
  zip: '',
  hoaMonthly: 0,
  utilitiesMonthly: 0,
  pointsCreditsNet: 0,
  grossMonthlyIncome: '',
});

function formatAssumptionValue(key, value) {
  // Every current assumption is a rate/fraction except none here are currency.
  return formatRate(value, key === 'pmiRemovalLtv' ? 0 : key.endsWith('Growth') ? 1 : 2);
}

export function useMortgage() {
  const [step, setStep] = useState(0);
  const [inputs, setInputs] = useState(initialInputs);
  const [overrides, setOverrides] = useState({});
  const [editedInputs, setEditedInputs] = useState(() => new Set());

  const defaults = useMemo(() => getDefaultAssumptions(), []);

  const resolvedAssumptions = useMemo(() => {
    const out = {};
    Object.keys(defaults).forEach((key) => {
      const has = Object.prototype.hasOwnProperty.call(overrides, key);
      out[key] = { value: has ? Number(overrides[key]) : defaults[key].value };
    });
    return out;
  }, [defaults, overrides]);

  const engineInputs = useMemo(
    () => ({
      homePrice: Number(inputs.homePrice) || 0,
      downPaymentPct: Number(inputs.downPaymentPct) || 0,
      loanTerm: Number(inputs.loanTerm) || 30,
      hoaMonthly: Number(inputs.hoaMonthly) || 0,
      utilitiesMonthly: Number(inputs.utilitiesMonthly) || 0,
      pointsCreditsNet: Number(inputs.pointsCreditsNet) || 0,
      grossMonthlyIncome: Number(inputs.grossMonthlyIncome) || 0,
    }),
    [inputs]
  );

  const result = useMemo(() => calculate(engineInputs, resolvedAssumptions), [engineInputs, resolvedAssumptions]);

  const overriddenKeys = useMemo(() => Object.keys(overrides), [overrides]);

  const composition = useMemo(
    () =>
      computeComposition({
        assumptions: defaults,
        overridden: overriddenKeys,
        directInputs: DIRECT_INPUTS,
        editedInputs,
      }),
    [defaults, overriddenKeys, editedInputs]
  );

  // "Why your estimate changed": per overridden monthly-affecting assumption,
  // the dollar impact on the true monthly carrying cost vs. the default.
  const whyChanged = useMemo(() => {
    return overriddenKeys
      .filter((key) => MONTHLY_KEYS.has(key))
      .map((key) => {
        const reverted = { ...resolvedAssumptions, [key]: { value: defaults[key].value } };
        const revertedResult = calculate(engineInputs, reverted);
        const delta = result.tiers.trueCarrying - revertedResult.tiers.trueCarrying;
        return {
          key,
          label: ASSUMPTION_LABELS[key] || key,
          fromText: formatAssumptionValue(key, defaults[key].value),
          toText: formatAssumptionValue(key, Number(overrides[key])),
          delta,
        };
      })
      .filter((it) => Math.abs(it.delta) >= 0.005 || it.fromText !== it.toText);
  }, [overriddenKeys, resolvedAssumptions, defaults, engineInputs, result, overrides]);

  const setInput = useCallback((key, value) => {
    setEditedInputs((prev) => {
      const next = new Set(prev);
      next.add(key);
      return next;
    });
    setInputs((prev) => ({ ...prev, [key]: value }));
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
    setStep(0);
  }, []);

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
    step,
    inputs,
    overrides,
    overriddenKeys,
    editedInputs,
    defaults,
    result,
    composition,
    whyChanged,
    setInput,
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
