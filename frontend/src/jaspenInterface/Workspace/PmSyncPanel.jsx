import React, { useEffect, useMemo, useState } from 'react';
import { Jaspen } from './JaspenClient';
const COLOR = { navy:'#161f3b', navy2:'#2c3656', ink:'#5a6585', mute:'#8a93ad', line:'#e4e8f0', line2:'#f1f3f8', rose:'#a0036c', roseTint:'#fbeaf3', greenInk:'#0e6b3f' };

const POLICIES = [
  ['latest_wins', 'Use the most recent change'],
  ['prefer_external', 'Jira wins'],
  ['prefer_jaspen', 'Jaspen wins'],
  ['manual_review', 'Ask me each time'],
];

const buttonStyle = {
  border: `1px solid ${COLOR.line}`, borderRadius: 8, background: '#fff', color: COLOR.navy,
  padding: '8px 12px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
};

function Choice({ checked, onClick, title, detail }) {
  return <button type="button" onClick={onClick} aria-pressed={checked} style={{
    textAlign: 'left', border: `1px solid ${checked ? COLOR.rose : COLOR.line}`,
    boxShadow: checked ? `0 0 0 2px ${COLOR.roseTint}` : 'none', borderRadius: 9,
    background: checked ? COLOR.roseTint : '#fff', padding: '10px 12px', cursor: 'pointer',
  }}>
    <div style={{ color: COLOR.navy, fontSize: 12.5, fontWeight: 650 }}>{title}</div>
    {detail && <div style={{ color: COLOR.mute, fontSize: 11.5, marginTop: 3 }}>{detail}</div>}
  </button>;
}

export default function PmSyncPanel({ threadId, planKey, taskCount = 0 }) {
  const [binding, setBinding] = useState(null);
  const [open, setOpen] = useState(false);
  const [projects, setProjects] = useState([]);
  const [projectKey, setProjectKey] = useState('');
  const [mode, setMode] = useState('');
  const [policy, setPolicy] = useState('');
  const [issueType, setIssueType] = useState('Task');
  const [groupEpics, setGroupEpics] = useState(true);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [connect, setConnect] = useState(null);

  const refresh = async () => {
    if (!threadId || !planKey) return;
    try {
      const data = await Jaspen.listPmSyncBindings(threadId, planKey);
      setBinding((data?.bindings || [])[0] || null);
    } catch (_) { /* an unavailable optional sync panel must not block the plan */ }
  };
  useEffect(() => { refresh(); }, [threadId, planKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedProject = useMemo(() => projects.find((p) => p.key === projectKey), [projects, projectKey]);

  const begin = async () => {
    setOpen(true); setBusy(true); setError('');
    try {
      const [projectData, previewData] = await Promise.all([
        Jaspen.listJiraProjects(), Jaspen.previewPmSync(threadId, planKey, true),
      ]);
      setProjects(projectData?.projects || []);
      setPreview(previewData?.preview || null);
    } catch (e) {
      const message = String(e?.message || e || 'Could not load Jira.');
      setError(message);
      if (/not connected|configuration is missing/i.test(message)) {
        setConnect({ jira_base_url: '', jira_email: '', jira_api_token: '' });
      }
    } finally { setBusy(false); }
  };

  const saveConnection = async () => {
    setBusy(true); setError('');
    try {
      await Jaspen.updateConnectorSettings('jira_sync', { ...connect, connection_status: 'connected' });
      await Jaspen.checkConnectorSetup('jira_sync');
      setConnect(null);
      const data = await Jaspen.listJiraProjects();
      setProjects(data?.projects || []);
      const p = await Jaspen.previewPmSync(threadId, planKey, groupEpics);
      setPreview(p?.preview || null);
    } catch (e) { setError(String(e?.message || e || 'Could not connect Jira.')); }
    finally { setBusy(false); }
  };

  const updatePreview = async (next) => {
    setGroupEpics(next);
    try {
      const data = await Jaspen.previewPmSync(threadId, planKey, next);
      setPreview(data?.preview || null);
    } catch (e) { setError(String(e?.message || e)); }
  };

  const send = async () => {
    setBusy(true); setError('');
    try {
      const data = await Jaspen.createPmSyncBinding({
        thread_id: threadId, plan_key: planKey, connector_id: 'jira_sync',
        external_container_id: projectKey, mode, conflict_policy: policy,
        config: { task_issue_type: issueType, group_under_epics: groupEpics },
      });
      setBinding(data?.binding || data?.result?.binding || null);
      if (data?.result?.errors?.length) setError(`${data.result.failed} item(s) need attention. Retry will continue without duplicates.`);
      else setOpen(false);
    } catch (e) { setError(String(e?.message || e || 'Send failed.')); }
    finally { setBusy(false); }
  };

  const syncNow = async () => {
    setBusy(true); setError('');
    try {
      const data = await Jaspen.syncPmBinding(binding.id);
      setBinding(data?.result?.binding || data?.binding || binding);
      if (data?.result?.errors?.length) setError(`${data.result.failed} item(s) failed. Retry will continue from saved links.`);
    } catch (e) { setError(String(e?.message || e || 'Sync failed.')); }
    finally { setBusy(false); }
  };

  if (binding) return <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, flexWrap: 'wrap' }}>
    <span style={{ ...buttonStyle, cursor: 'default', color: binding.status === 'error' ? '#b91c1c' : COLOR.greenInk }}>
      ● {binding.status === 'active' ? 'Synced with Jira' : `Jira · ${binding.status}`}
    </span>
    <button type="button" onClick={syncNow} disabled={busy} style={buttonStyle}>{busy ? 'Syncing…' : 'Sync now'}</button>
    {binding.external_container_url && <a href={binding.external_container_url} target="_blank" rel="noreferrer" style={{ ...buttonStyle, textDecoration: 'none' }}>View in Jira</a>}
    {error && <span role="alert" style={{ color: '#b91c1c', fontSize: 11.5 }}>{error}</span>}
  </div>;

  return <>
    <button type="button" onClick={begin} disabled={!taskCount || !planKey} style={buttonStyle}>Send to Jira</button>
    {open && <div role="dialog" aria-modal="true" aria-label="Send execution plan to Jira" style={{
      position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(22,31,59,.42)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div style={{ width: 620, maxWidth: '100%', maxHeight: '88vh', overflow: 'auto', background: '#fff', borderRadius: 14, padding: 24, boxShadow: '0 24px 70px rgba(22,31,59,.25)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <div><h2 style={{ margin: 0, color: COLOR.navy, fontSize: 20 }}>Send this plan to Jira</h2><p style={{ margin: '6px 0 18px', color: COLOR.ink, fontSize: 13 }}>Choose exactly where it goes and how future changes should be handled.</p></div>
          <button type="button" aria-label="Close" onClick={() => setOpen(false)} style={{ ...buttonStyle, width: 34, height: 34 }}>×</button>
        </div>
        {error && <div role="alert" style={{ padding: 10, borderRadius: 8, background: '#fff1f2', color: '#9f1239', fontSize: 12, marginBottom: 14 }}>{error}</div>}
        {connect ? <div style={{ display: 'grid', gap: 10 }}>
          <strong style={{ color: COLOR.navy }}>Connect Jira</strong>
          <input aria-label="Jira site URL" placeholder="https://company.atlassian.net" value={connect.jira_base_url} onChange={(e) => setConnect({ ...connect, jira_base_url: e.target.value })} />
          <input aria-label="Jira email" placeholder="you@company.com" value={connect.jira_email} onChange={(e) => setConnect({ ...connect, jira_email: e.target.value })} />
          <input aria-label="Jira API token" type="password" placeholder="API token" value={connect.jira_api_token} onChange={(e) => setConnect({ ...connect, jira_api_token: e.target.value })} />
          <button type="button" onClick={saveConnection} disabled={busy || !connect.jira_base_url || !connect.jira_email || !connect.jira_api_token} style={buttonStyle}>{busy ? 'Connecting…' : 'Connect and continue'}</button>
        </div> : <div style={{ display: 'grid', gap: 16 }}>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: COLOR.navy, fontWeight: 650 }}>Destination project
            <select aria-label="Destination project" value={projectKey} onChange={(e) => setProjectKey(e.target.value)} style={{ padding: 9, border: `1px solid ${COLOR.line}`, borderRadius: 8 }}><option value="">Choose a Jira project…</option>{projects.map((p) => <option key={p.key} value={p.key}>{p.key} · {p.name}</option>)}</select>
          </label>
          <div style={{ display: 'flex', gap: 14 }}>
            <label style={{ flex: 1, display: 'grid', gap: 5, fontSize: 12, color: COLOR.navy, fontWeight: 650 }}>Issue type<select aria-label="Task issue type" value={issueType} onChange={(e) => setIssueType(e.target.value)} style={{ padding: 9, border: `1px solid ${COLOR.line}`, borderRadius: 8 }}><option>Task</option><option>Story</option></select></label>
            <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: COLOR.navy }}><input type="checkbox" checked={groupEpics} onChange={(e) => updatePreview(e.target.checked)} /> Group tasks under epics</label>
          </div>
          <div><div style={{ color: COLOR.navy, fontSize: 12, fontWeight: 700, marginBottom: 7 }}>Sync mode · required</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}><Choice checked={mode === 'two_way'} onClick={() => setMode('two_way')} title="Keep both in sync" detail="Jira and Jaspen can update the plan." /><Choice checked={mode === 'push_only'} onClick={() => setMode('push_only')} title="Push only" detail="Only Jaspen sends updates to Jira." /></div></div>
          <div><div style={{ color: COLOR.navy, fontSize: 12, fontWeight: 700, marginBottom: 7 }}>If the same field changes in both places · required</div><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>{POLICIES.map(([value, label]) => <Choice key={value} checked={policy === value} onClick={() => setPolicy(value)} title={label} />)}</div></div>
          {preview && <div style={{ background: COLOR.line2, borderRadius: 9, padding: 12, color: COLOR.navy2, fontSize: 12.5 }}>Will create {preview.epics} epic{preview.epics === 1 ? '' : 's'}, {preview.issues} issue{preview.issues === 1 ? '' : 's'}, and {preview.dependencies} “Blocks” link{preview.dependencies === 1 ? '' : 's'}{selectedProject ? ` in ${selectedProject.key}` : ''}. {preview.unmapped_owners} owner{preview.unmapped_owners === 1 ? '' : 's'} will be left unassigned.</div>}
          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}><button type="button" onClick={() => setOpen(false)} style={buttonStyle}>Cancel</button><button type="button" onClick={send} disabled={busy || !projectKey || !mode || !policy} style={{ ...buttonStyle, background: COLOR.rose, color: '#fff', borderColor: COLOR.rose }}>{busy ? 'Sending…' : 'Send'}</button></div>
        </div>}
      </div>
    </div>}
  </>;
}
