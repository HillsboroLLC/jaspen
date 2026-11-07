const PLAN_MUTATION_TOOLS = ['update_wbs_task', 'add_wbs_task', 'add_wbs_dependency', 'remove_wbs_task', 'generate_execution_plan'];

// Whether a successful tool result changed a plan, so the open plan refreshes.
// A commitment the capture step saved onto a plan task changes the plan too.
export function planChangedByMutation(mutation) {
  const tool = String(mutation?.tool || '').trim();
  if (PLAN_MUTATION_TOOLS.includes(tool)) return true;
  const summary = mutation?.result_summary || {};
  if (tool === 'confirm_task_commitment') return !summary.already_committed;
  if (tool === 'record_decision_context') return summary?.task_commitment?.status === 'recorded';
  return false;
}
