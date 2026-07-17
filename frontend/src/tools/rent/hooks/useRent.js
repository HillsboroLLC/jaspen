// =====================================================
// Rent calculator — flow state hook.
// Owns inputs, benchmark overrides, edited-input tracking, and step navigation;
// derives the engine result, Estimate Composition, and the "Why your estimate
// changed" explanations (impact on the 3-year cost for growth-rate overrides).
// =====================================================

import { useCallback, useMemo, useState } from 'react';
import { calculate } from '../engine/calculator';
import { getDefaultAssumptions, DIRECT_INPUTS } from '../data/benchmarks';
import { computeComposition } from '../../shared/composition';
import { formatRate } from '../../shared/formatting';
import { ASSUMPTION_LABELS } from '../config/questions';
import { analytics } from '../services/analytics';

const EXPLAIN_KEYS = new Set(['annualRentIncrease', 'annualFeeIncrease', 'annualUtilityIncrease', 'annualInsuranceIncrease']);

const initialInputs = () => ({
  advertisedRent: 2000,
  leaseTermMonths: 12,
  freeMonths: 0,
  zip: '',
  monthlyParking: 0,
  monthlyPetRent: 0,
  monthlyOtherFees: 0,
  monthlyInsurance: 0,
  monthlyUtilities: 0,
  refundablePetDeposit: 0,
  nonrefundableFees: 0,
  nonrefundablePetFee: 0,
  movingSetup: 0,
  lastMonthPrepaid: 0,
  grossMonthlyIncome: '',
});

function threeYearNet(result) {
  const h = result.horizons.find((x) => x.years === 3);
  return h ? h.netCostExclRefundable : 0;
}

export function useRent() {
  const [step, setStep] = useState(0);
  const [inputs, setInputs] = useState(initialInputs);
  const [overrides, setOverrides] = useState({});
  const [editedInputs, setEditedInputs] = useState(() => new Set());

  const defaults = useMemo(() => getDefaultAssumptions(inputs), [inputs]);

  const resolvedAssumptions = useMemo(() => {
    const out = {};
    Object.keys(defaults).forEach((key) => {
      const has = Object.prototype.hasOwnProperty.call(overrides, key);
      out[key] = { value: has ? Number(overrides[key]) : defaults[key].value };
    });
    return out;
  }, [defaults, overrides]);

  const engineInputs = useMemo(() => {
    const clone = {};
    DIRECT_INPUTS.forEach((k) => {
      clone[k] = inputs[k] === '' ? 0 : Number(inputs[k]) || 0;
    });
    return clone;
  }, [inputs]);

  const result = useMemo(() => calculate(engineInputs, resolvedAssumptions), [engineInputs, resolvedAssumptions]);

  const overriddenKeys = useMemo(() => Object.keys(overrides), [overrides]);

  const composition = useMemo(
    () => computeComposition({ assumptions: defaults, overridden: overriddenKeys, directInputs: DIRECT_INPUTS, editedInputs }),
    [defaults, overriddenKeys, editedInputs]
  );

  const whyChanged = useMemo(() => {
    return overriddenKeys
      .filter((key) => EXPLAIN_KEYS.has(key))
      .map((key) => {
        const reverted = { ...resolvedAssumptions, [key]: { value: defaults[key].value } };
        const revertedResult = calculate(engineInputs, reverted);
        const delta = threeYearNet(result) - threeYearNet(revertedResult);
        return {
          key,
          label: ASSUMPTION_LABELS[key] || key,
          fromText: formatRate(defaults[key].value, 1),
          toText: formatRate(Number(overrides[key]), 1),
          delta,
        };
      })
      .filter((it) => Math.abs(it.delta) >= 0.5 || it.fromText !== it.toText);
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

  const isAssumptionOverridden = useCallback((key) => Object.prototype.hasOwnProperty.call(overrides, key), [overrides]);
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
