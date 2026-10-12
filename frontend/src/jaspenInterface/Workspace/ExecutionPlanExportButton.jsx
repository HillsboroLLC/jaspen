import React, { useCallback, useState } from 'react';
import { Jaspen } from './JaspenClient';
import { useToast } from '../../shared/components/Toast';

export const downloadExecutionPlan = async ({ threadId, scorecardId }) => {
  const result = await Jaspen.downloadWbsXlsx(String(threadId || '').trim(), {
    scorecardId: String(scorecardId || '').trim() || undefined,
  });
  if (!(result?.blob instanceof Blob)) throw new Error('The export did not return a file.');
  const url = URL.createObjectURL(result.blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = result.filename || 'jaspen-execution-plan.xlsx';
  document.body.appendChild(link);
  link.click(); link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1500);
  return result;
};

export default function ExecutionPlanExportButton({ threadId, scorecardId, disabled = false, compact = false }) {
  const [busy, setBusy] = useState(false);
  const { showToast } = useToast();
  const run = useCallback(async () => {
    if (!threadId || busy) return;
    setBusy(true);
    try {
      await downloadExecutionPlan({ threadId, scorecardId });
      showToast('Exported execution plan Excel workbook', 'success');
    } catch (error) {
      showToast(error?.message || 'Could not export the execution plan as Excel.', 'error');
    } finally { setBusy(false); }
  }, [busy, scorecardId, showToast, threadId]);
  return <button type="button" onClick={() => { void run(); }} disabled={disabled || busy || !threadId}
    aria-label="Export to Excel" style={{ border:'1px solid #e4e8f0', borderRadius:8, background:'#fff', color:'#161f3b', padding:compact ? '6px 9px' : '8px 12px', fontSize:12, fontWeight:600, cursor:'pointer' }}>
    {busy ? 'Exporting…' : 'Export to Excel'}
  </button>;
}
