import { shouldCreateScenarioAfterUpdateError } from './ScenarioModeler';

it('creates only when the saved scenario is gone, never on a D4 conflict', () => {
  expect(shouldCreateScenarioAfterUpdateError({ status: 404 })).toBe(true);
  expect(shouldCreateScenarioAfterUpdateError({
    status: 409,
    data: { code: 'revision_conflict' },
  })).toBe(false);
  expect(shouldCreateScenarioAfterUpdateError({ status: 500 })).toBe(false);
});
