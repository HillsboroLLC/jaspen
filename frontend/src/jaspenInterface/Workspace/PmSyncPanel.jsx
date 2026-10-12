import React, { useEffect, useMemo, useRef, useState } from 'react';
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

function Choice({ checked, onClick, title, detail, disabled = false }) {
  return <button type="button" onClick={onClick} aria-pressed={checked} disabled={disabled} style={{
    textAlign: 'left', border: `1px solid ${checked ? COLOR.rose : COLOR.line}`,
    boxShadow: checked ? `0 0 0 2px ${COLOR.roseTint}` : 'none', borderRadius: 9,
    background: checked ? COLOR.roseTint : '#fff', padding: '10px 12px',
    cursor: disabled ? 'not-allowed' : 'pointer', opacity: disabled ? 0.55 : 1,
  }}>
    <div style={{ color: COLOR.navy, fontSize: 12.5, fontWeight: 650 }}>{title}</div>
    {detail && <div style={{ color: COLOR.mute, fontSize: 11.5, marginTop: 3 }}>{detail}</div>}
  </button>;
}

export default function PmSyncPanel({ threadId, planKey, taskCount = 0, compact = false }) {
  const [binding, setBinding] = useState(null);
  const [open, setOpen] = useState(false);
  const [tool, setTool] = useState('');
  const [projects, setProjects] = useState([]);
  const [projectKey, setProjectKey] = useState('');
  const [mode, setMode] = useState('two_way');
  const [policy, setPolicy] = useState('latest_wins');
  const [issueType, setIssueType] = useState('Task');
  const [groupEpics, setGroupEpics] = useState(true);
  const [preview, setPreview] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [connect, setConnect] = useState(null);
  const [connectionTested, setConnectionTested] = useState(false);
  const [logs, setLogs] = useState([]);
  const [newProject, setNewProject] = useState(null);
  const openedSync = useRef('');

  const refresh = async () => {
    if (!threadId || !planKey) return;
    try {
      const data = await Jaspen.listPmSyncBindings(threadId, planKey);
      const next = (data?.bindings || [])[0] || null;
      setBinding(next);
      if (next) {
        const detail = await Jaspen.getPmSyncBinding(next.id);
        setLogs(detail?.logs || []);
      }
    } catch (_) { /* an unavailable optional sync panel must not block the plan */ }
  };
  useEffect(() => { refresh(); }, [threadId, planKey]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!binding?.id || binding.status === 'paused' || openedSync.current === binding.id) return;
    openedSync.current = binding.id;
    Jaspen.syncPmBinding(binding.id).then((data) => {
      setBinding((current) => ({ ...(current || {}), ...(data?.result?.binding || data?.binding || {}) }));
      setLogs(data?.logs || []);
    }).catch((e) => setError(String(e?.message || e || 'Automatic sync failed. Use Retry.')));
  }, [binding]);

  const selectedProject = useMemo(() => projects.find((p) => p.key === projectKey), [projects, projectKey]);

  const begin = () => {
    setOpen(true); setTool(''); setConnect(null); setConnectionTested(false);
    setProjects([]); setProjectKey(''); setPreview(null); setError('');
  };

  const chooseTool = async (nextTool) => {
    if (nextTool !== 'jira') return;
    setTool(nextTool); setBusy(true); setError('');
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

  const testConnection = async () => {
    setBusy(true); setError('');
    try {
      await Jaspen.testJiraConnection(connect);
      setConnectionTested(true);
    } catch (e) { setConnectionTested(false); setError(String(e?.message || e || 'Could not connect Jira.')); }
    finally { setBusy(false); }
  };

  const saveConnection = async () => {
    setBusy(true); setError('');
    try {
      if (!connectionTested) throw new Error('Test the connection before saving it.');
      await Jaspen.connectJira(connect);
      setConnect(null);
      const data = await Jaspen.listJiraProjects();
      setProjects(data?.projects || []);
      const p = await Jaspen.previewPmSync(threadId, planKey, groupEpics);
      setPreview(p?.preview || null);
    } catch (e) { setError(String(e?.message || e || 'Could not connect Jira.')); }
    finally { setBusy(false); }
  };

  const createProject = async () => {
    setBusy(true); setError('');
    try {
      const data = await Jaspen.createJiraProject(newProject);
      const project = data?.project;
      if (!project?.key) throw new Error('Jira did not return the new project.');
      setProjects((current) => [...current.filter((row) => row.key !== project.key), project]);
      setProjectKey(project.key); setNewProject(null);
    } catch (e) { setError(String(e?.message || e || 'Could not create the Jira project.')); }
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
      setBinding((current) => ({ ...(current || {}), ...(data?.result?.binding || data?.binding || {}) }));
      setLogs(data?.logs || []);
      if (data?.result?.errors?.length) setError(`${data.result.failed} item(s) failed. Retry will continue from saved links.`);
    } catch (e) { setError(String(e?.message || e || 'Sync failed.')); }
    finally { setBusy(false); }
  };

  const toggleTwoWay = async (enabled) => {
    setBusy(true); setError('');
    try {
      const data = await Jaspen.updatePmSyncBinding(binding.id, { mode: enabled ? 'two_way' : 'push_only' });
      setBinding(data?.binding || { ...binding, mode: enabled ? 'two_way' : 'push_only' });
    } catch (e) { setError(String(e?.message || e || 'Could not change sync mode.')); }
    finally { setBusy(false); }
  };

  if (binding) return <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', maxWidth: compact ? 430 : 'none' }}>
    <span style={{ ...buttonStyle, cursor: 'default', color: binding.status === 'error' ? '#b91c1c' : COLOR.greenInk }}>
      ● {binding.status === 'active' ? 'Synced with Jira' : `Jira · ${binding.status}`}{binding.last_success_at ? ` · ${new Date(binding.last_success_at).toLocaleString()}` : ''}
    </span>
    <label style={{ ...buttonStyle, display:'inline-flex', gap:6, alignItems:'center' }}><input type="checkbox" checked={binding.mode === 'two_way'} onChange={(e) => toggleTwoWay(e.target.checked)} />Two-way sync</label>
    <button type="button" onClick={syncNow} disabled={busy} style={buttonStyle}>{busy ? 'Syncing…' : 'Sync now'}</button>
    {binding.external_container_url && <a href={binding.external_container_url} target="_blank" rel="noreferrer" style={{ ...buttonStyle, textDecoration: 'none' }}>View in Jira</a>}
    {error && <span role="alert" style={{ color: '#b91c1c', fontSize: 11.5 }}>{error}</span>}
    {logs[0] && <span style={{ color: COLOR.mute, fontSize: 11.5 }}>Last sync: {logs[0].status} · {logs[0].items_synced || 0} changes{(logs[0].sync_metadata?.conflicts || []).length ? ` · ${logs[0].sync_metadata.conflicts.length} need review` : ''}</span>}
    {logs.length > 0 && <details style={{ fontSize:11.5, color:COLOR.ink }}><summary style={{ cursor:'pointer' }}>Sync history</summary><div style={{ position:'absolute', zIndex:20, background:'#fff', border:`1px solid ${COLOR.line}`, borderRadius:8, padding:10, width:330, boxShadow:'0 10px 30px rgba(22,31,59,.12)' }}>{logs.slice(0, 5).map((log) => <div key={log.id} style={{ padding:'5px 0', borderBottom:`1px solid ${COLOR.line2}` }}><strong>{log.status}</strong> · {log.items_synced || 0} changes · {log.created_at ? new Date(log.created_at).toLocaleString() : 'just now'}{(log.sync_metadata?.conflicts || []).map((conflict) => <div key={`${conflict.task_id}-${conflict.field}`} style={{ color:'#9f1239' }}>{conflict.task_id}: choose the {conflict.field} value</div>)}{(log.sync_metadata?.errors || []).map((item, index) => <div key={index} style={{ color:'#9f1239' }}>{item.error}</div>)}</div>)}</div></details>}
  </div>;

  const close = () => { setOpen(false); setTool(''); setConnect(null); setError(''); };

  return <>
    <label style={{ ...buttonStyle, display:'inline-flex', gap:7, alignItems:'center', opacity: (!taskCount || !planKey) ? 0.55 : 1 }}>
      <input type="checkbox" checked={false} onChange={(e) => { if (e.target.checked) begin(); }} disabled={!taskCount || !planKey} />
      Sync execution plan
    </label>
    {open && <div role="dialog" aria-modal="true" aria-label="Set up execution plan sync" style={{
      position: 'fixed', inset: 0, zIndex: 10000, background: 'rgba(22,31,59,.42)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', padding: 24,
    }}>
      <div style={{ width: 620, maxWidth: '100%', maxHeight: '88vh', overflow: 'auto', background: '#fff', borderRadius: 14, padding: 24, boxShadow: '0 24px 70px rgba(22,31,59,.25)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
          <div><h2 style={{ margin: 0, color: COLOR.navy, fontSize: 20 }}>Sync this execution plan</h2><p style={{ margin: '6px 0 18px', color: COLOR.ink, fontSize: 13 }}>{tool ? 'Connect this plan to a project.' : 'Choose where this plan should stay in sync.'}</p></div>
          <button type="button" aria-label="Close" onClick={close} style={{ ...buttonStyle, width: 34, height: 34 }}>×</button>
        </div>
        {error && <div role="alert" style={{ padding: 10, borderRadius: 8, background: '#fff1f2', color: '#9f1239', fontSize: 12, marginBottom: 14 }}>{error}</div>}
        {!tool ? <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10 }}>
          <Choice checked={false} onClick={() => chooseTool('jira')} title="Jira" detail="Connect an existing project or create a new one" />
          <Choice checked={false} disabled title="Smartsheet" detail="Coming soon" />
        </div> : connect ? <div style={{ display: 'grid', gap: 10 }}>
          <strong style={{ color: COLOR.navy }}>Connect Jira</strong>
          <input aria-label="Jira site URL" placeholder="https://company.atlassian.net" value={connect.jira_base_url} onChange={(e) => setConnect({ ...connect, jira_base_url: e.target.value })} />
          <input aria-label="Jira email" placeholder="you@company.com" value={connect.jira_email} onChange={(e) => setConnect({ ...connect, jira_email: e.target.value })} />
          <input aria-label="Jira API token" type="password" placeholder="API token" value={connect.jira_api_token} onChange={(e) => setConnect({ ...connect, jira_api_token: e.target.value })} />
          <div style={{ color:COLOR.ink, fontSize:12 }}>Create an Atlassian API token, then paste it here. <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noreferrer">Open Atlassian API tokens</a></div>
          <div style={{ display:'flex', gap:8 }}><button type="button" onClick={() => { setTool(''); setConnect(null); setError(''); }} style={buttonStyle}>Back</button><button type="button" onClick={testConnection} disabled={busy || !connect.jira_base_url || !connect.jira_email || !connect.jira_api_token} style={buttonStyle}>{busy ? 'Testing…' : 'Test connection'}</button><button type="button" onClick={saveConnection} disabled={busy || !connectionTested} style={{ ...buttonStyle, border:`1px solid ${connectionTested ? COLOR.rose : COLOR.line}`, background:connectionTested ? COLOR.rose : '#fff', color:connectionTested ? '#fff' : COLOR.mute }}>Save and continue</button></div>
        </div> : <div style={{ display: 'grid', gap: 16 }}>
          <label style={{ display: 'grid', gap: 5, fontSize: 12, color: COLOR.navy, fontWeight: 650 }}>Destination project
            <select aria-label="Destination project" value={projectKey} onChange={(e) => setProjectKey(e.target.value)} style={{ padding: 9, border: `1px solid ${COLOR.line}`, borderRadius: 8 }}><option value="">Choose a Jira project…</option>{projects.map((p) => <option key={p.key} value={p.key}>{p.key} · {p.name}</option>)}</select>
          </label>
          {!newProject ? <button type="button" onClick={() => setNewProject({ key:'', name:'' })} style={buttonStyle}>Create a new Jira project</button> : <div style={{ display:'grid', gridTemplateColumns:'120px 1fr auto', gap:8 }}><input aria-label="New project key" placeholder="KEY" value={newProject.key} onChange={(e) => setNewProject({ ...newProject, key:e.target.value.toUpperCase() })} /><input aria-label="New project name" placeholder="Project name" value={newProject.name} onChange={(e) => setNewProject({ ...newProject, name:e.target.value })} /><button type="button" onClick={createProject} disabled={busy || !newProject.key || !newProject.name} style={buttonStyle}>Create</button></div>}
          <div style={{ display: 'flex', gap: 14 }}>
            <label style={{ flex: 1, display: 'grid', gap: 5, fontSize: 12, color: COLOR.navy, fontWeight: 650 }}>Issue type<select aria-label="Task issue type" value={issueType} onChange={(e) => setIssueType(e.target.value)} style={{ padding: 9, border: `1px solid ${COLOR.line}`, borderRadius: 8 }}><option>Task</option><option>Story</option></select></label>
            <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: COLOR.navy }}><input type="checkbox" checked={groupEpics} onChange={(e) => updatePreview(e.target.checked)} /> Group tasks under epics</label>
          </div>
          <label style={{ display:'flex', alignItems:'center', gap:8, color:COLOR.navy, fontSize:12, fontWeight:650 }}><input type="checkbox" checked={mode === 'two_way'} onChange={(e) => setMode(e.target.checked ? 'two_way' : 'push_only')} />Two-way sync <span style={{ color:COLOR.mute, fontWeight:400 }}>(on by default; off is push only)</span></label>
          <details><summary style={{ color:COLOR.navy, fontSize:12, fontWeight:700, cursor:'pointer' }}>Advanced conflict handling</summary><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop:8 }}>{POLICIES.map(([value, label]) => <Choice key={value} checked={policy === value} onClick={() => setPolicy(value)} title={label} />)}</div></details>
          {preview && <div style={{ background: COLOR.line2, borderRadius: 9, padding: 12, color: COLOR.navy2, fontSize: 12.5 }}>Will create {preview.epics} epic{preview.epics === 1 ? '' : 's'}, {preview.issues} issue{preview.issues === 1 ? '' : 's'}, and {preview.dependencies} “Blocks” link{preview.dependencies === 1 ? '' : 's'}{selectedProject ? ` in ${selectedProject.key}` : ''}. {preview.unmapped_owners} owner{preview.unmapped_owners === 1 ? '' : 's'} will be left unassigned.</div>}
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><button type="button" onClick={() => { setTool(''); setError(''); }} style={buttonStyle}>Back</button><div style={{ display:'flex', gap:8 }}><button type="button" onClick={close} style={buttonStyle}>Cancel</button><button type="button" onClick={send} disabled={busy || !projectKey} style={{ ...buttonStyle, border:`1px solid ${COLOR.rose}`, background: COLOR.rose, color: '#fff' }}>{busy ? 'Linking…' : 'Link project'}</button></div></div>
        </div>}
      </div>
    </div>}
  </>;
}
