import React from 'react';

// Shown on a plan Jaspen built in code from the decision because the AI plan
// could not be completed. Informational, not an error: the plan is usable.
export default function StarterPlanNote({ plan, onRefine = null, style = {} }) {
  if (plan?.generation_status !== 'starter_plan') return null;
  const note = String(plan?.starter_plan_note || '').trim()
    || 'Starter plan built from your decision; ask Jaspen to refine it.';
  return (
    <div
      role="status"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 12,
        boxSizing: 'border-box',
        padding: '8px 12px',
        border: '1px solid #cfe0e6',
        borderRadius: 8,
        background: '#eef5f7',
        color: '#1b2342',
        fontSize: 12.5,
        lineHeight: 1.4,
        ...style,
      }}
    >
      <span style={{ flex: 1, minWidth: 0 }}>{note}</span>
      {onRefine && (
        <button
          type="button"
          onClick={onRefine}
          style={{
            flex: '0 0 auto',
            padding: '5px 12px',
            border: '1px solid #1b2342',
            borderRadius: 6,
            background: '#fff',
            color: '#1b2342',
            cursor: 'pointer',
            fontSize: 12,
            fontWeight: 600,
          }}
        >
          Ask Jaspen to refine
        </button>
      )}
    </div>
  );
}
