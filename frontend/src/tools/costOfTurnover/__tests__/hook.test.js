import { act, renderHook } from '@testing-library/react';
import { useCostOfTurnover } from '../hooks/useCostOfTurnover';

describe('useCostOfTurnover', () => {
  it('moves a salary edit into organization inputs without changing benchmarks', () => {
    const { result } = renderHook(() => useCostOfTurnover());
    const originalDefaults = Object.fromEntries(
      Object.entries(result.current.defaults).map(([key, value]) => [key, value.value])
    );

    expect(result.current.builtUsing.org).toBe(0);

    act(() => result.current.setInput('salary', 151000));

    expect(result.current.builtUsing.org).toBe(6);
    expect(result.current.builtUsing.research).toBe(76);
    expect(
      Object.fromEntries(
        Object.entries(result.current.defaults).map(([key, value]) => [key, value.value])
      )
    ).toEqual(originalDefaults);
  });

  it('restores all inputs, overrides, and composition state', () => {
    const { result } = renderHook(() => useCostOfTurnover());

    act(() => {
      result.current.setInput('salary', 151000);
      result.current.overrideAssumption('costPerHire', 8000);
    });
    expect(result.current.hasEdits).toBe(true);

    act(() => result.current.resetEstimate());

    expect(result.current.inputs.salary).toBe(120000);
    expect(result.current.overriddenKeys).toEqual([]);
    expect(result.current.builtUsing.org).toBe(0);
    expect(result.current.hasEdits).toBe(false);
  });
});
