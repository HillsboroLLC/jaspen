import { calculateEstimate } from './EnterpriseInvestmentCalculator';

const estimate = (overrides = {}) => calculateEstimate({
  participants: 10, teams: 1, usage: 'standard', requirements: [], billing: 'annual', ...overrides,
});

test('calculates exact Business annual seat pricing through the 10-user cap', () => {
  expect(estimate({ participants: 10 }).annualLow).toBe(4788);
  expect(estimate({ participants: 10 }).price).toBe('$4,788 billed annually');
});

test('uses the documented Core, Scale, and Strategic boundaries', () => {
  expect(estimate({ participants: 11 }).price).toBe('$24,000–$36,000 annually');
  expect(estimate({ participants: 20 }).band).toBe('Enterprise Core');
  expect(estimate({ participants: 21 }).band).toBe('Enterprise Scale');
  expect(estimate({ participants: 50 }).band).toBe('Enterprise Scale');
  expect(estimate({ participants: 51 }).band).toBe('Enterprise Strategic');
});

test('weights complex requirements instead of counting checkboxes equally', () => {
  expect(estimate({ participants: 10, requirements: ['multiple_workspaces', 'enterprise_integrations'], usage: 'light' }).band).toBe('Enterprise Core');
  expect(estimate({ participants: 10, requirements: ['multiple_workspaces', 'enterprise_integrations', 'security_review'], usage: 'light' }).band).toBe('Enterprise Scale');
});

test('applies the methodology team and usage scores at their exact boundaries', () => {
  expect(estimate({ participants: 10, teams: 3, usage: 'standard' }).band).toBe('Enterprise Core');
  expect(estimate({ participants: 10, teams: 4, usage: 'standard' }).band).toBe('Enterprise Scale');
  expect(estimate({ participants: 11, usage: 'high' }).band).toBe('Enterprise Core');
  expect(estimate({ participants: 11, usage: 'high', requirements: ['multiple_workspaces', 'security_review'] }).band).toBe('Enterprise Scale');
});

test('uses the midpoint of a bounded range for leadership-time equivalence', () => {
  expect(estimate({ participants: 11 }).equivalentInvestment).toBe(30000);
  expect(estimate({ participants: 21 }).equivalentInvestment).toBe(60000);
  expect(estimate({ participants: 51 }).equivalentInvestment).toBe(72000);
});
