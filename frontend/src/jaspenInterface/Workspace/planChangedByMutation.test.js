import { planChangedByMutation } from './planRefresh';

test('captured task commitments refresh the open plan; other capture saves do not', () => {
  expect(planChangedByMutation({ tool: 'update_wbs_task' })).toBe(true);
  expect(planChangedByMutation({ tool: 'confirm_task_commitment', result_summary: { already_committed: false } })).toBe(true);
  expect(planChangedByMutation({ tool: 'confirm_task_commitment', result_summary: { already_committed: true } })).toBe(false);
  expect(planChangedByMutation({ tool: 'record_decision_context', result_summary: { task_commitment: { status: 'recorded' } } })).toBe(true);
  expect(planChangedByMutation({ tool: 'record_decision_context', result_summary: { kind: 'deadline' } })).toBe(false);
  expect(planChangedByMutation({ tool: 'record_option_decision' })).toBe(false);
});
