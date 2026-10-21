import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
const inputStyle = {
  width: '100%', boxSizing: 'border-box', border: `1px solid ${COLOR.line}`, borderRadius: 8,
  background: '#fff', color: COLOR.navy, padding: '10px 11px', fontSize: 13, outline: 'none',
};
const RECONNECT_MESSAGE = 'Your saved Jira connection no longer works. Enter a new API token to continue.';

// Plain words for the stored sync states; the codes themselves never reach users.
const BINDING_STATUS_LABELS = {
  active: 'Synced with Jira',
  partial: 'Synced · needs review',
  links_missing: 'Issues missing in Jira',
  error: 'Jira sync error',
  paused: 'Jira sync paused',
  reconnect_required: 'Reconnect Jira',
  disconnected: 'Unlinked from Jira',
};
const LOG_STATUS_LABELS = { success: 'Synced', partial: 'Partly synced', failed: 'Failed' };

export const bindingStatusLabel = (status) => BINDING_STATUS_LABELS[status] || 'Jira sync';
export const syncLogStatusLabel = (status) => LOG_STATUS_LABELS[status] || 'Sync';

export function syncOwnerLabel(binding) {
  const owner = binding?.sync_owner || {};
  return owner.name || owner.email || 'the person who connected Jira';
}

export function syncWarningMessage(binding) {
  const owner = syncOwnerLabel(binding);
  const code = binding?.sync_warning_code || binding?.pause_reason;
  const missing = Number(binding?.config?.missing_issue_count || 0);
  if (code === 'links_missing' || binding?.status === 'links_missing') {
    return `${missing} linked Jira issue${missing === 1 ? '' : 's'} no longer ${missing === 1 ? 'exists' : 'exist'} in ${binding?.external_container_id}.`;
  }
  if (code === 'authorization_expired' || binding?.status === 'reconnect_required') {
    return `Jira needs to be reconnected by ${owner} before this plan can sync.`;
  }
  if (code === 'sync_owner_left_organization' || code === 'sync_owner_unavailable') {
    return 'Sync is paused because the person who connected Jira no longer has access.';
  }
  if (code === 'credential_disconnected') {
    return `Jira was disconnected by ${owner}. Reconnect Jira before this plan can sync.`;
  }
  if (code === 'sync_failed' || binding?.status === 'error') {
    return `Jira sync needs attention. ${owner} can retry or reconnect Jira.`;
  }
  return '';
}

export function lastSyncSummary(logs) {
  const rows = Array.isArray(logs) ? logs : [];
  const latest = rows[0];
  if (!latest) return null;
  const latestAt = new Date(latest.created_at).getTime();
  const actionLogs = rows.filter((log, index) => {
    if (index === 0) return true;
    const createdAt = new Date(log?.created_at).getTime();
    return Number.isFinite(latestAt) && Number.isFinite(createdAt)
      && latestAt >= createdAt && latestAt - createdAt <= 60_000;
  });
  const statusRank = { success: 0, partial: 1, failed: 2 };
  const status = actionLogs.reduce((worst, log) => {
    const candidate = String(log?.status || '').toLowerCase();
    return (statusRank[candidate] ?? -1) > (statusRank[worst] ?? -1) ? candidate : worst;
  }, String(latest.status || 'success').toLowerCase());
  const conflicts = actionLogs.flatMap((log) => log?.sync_metadata?.conflicts || []);
  return {
    ...latest,
    status,
    items_synced: actionLogs.reduce((total, log) => total + (Number(log?.items_synced) || 0), 0),
    sync_metadata: { ...(latest.sync_metadata || {}), conflicts },
  };
}

function connectionDraft(info = {}) {
  return {
    jira_base_url: String(info?.base_url || ''),
    jira_email: String(info?.email || ''),
    jira_api_token: '',
  };
}

function isReconnectError(error) {
  return error?.status === 401 || error?.status === 403 || error?.data?.code === 'JIRA_RECONNECT_REQUIRED';
}

function friendlyJiraError(error, fallback) {
  if (isReconnectError(error)) return RECONNECT_MESSAGE;
  return String(error?.data?.error || error?.message || error || fallback);
}

function suggestedProjectKey(name) {
  const words = String(name || '').toUpperCase().match(/[A-Z0-9]+/g) || [];
  if (!words.length) return '';
  const initials = words.map((word) => word[0]).join('').slice(0, 10);
  if (initials.length >= 2) return initials;
  return words[0].slice(0, 10).padEnd(2, 'X');
}

function projectKeyError(key) {
  const raw = String(key || '').trim();
  if (raw.length > 10 || /[a-z]/.test(raw) || /^ATATT/i.test(raw)) {
    return 'That looks like an API token. Enter it under Jira connection instead.';
  }
  if (!/^[A-Z][A-Z0-9]{1,9}$/.test(raw)) {
    return 'Project key must be 2–10 uppercase letters or digits and start with a letter.';
  }
  return '';
}

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

export default function PmSyncPanel({ threadId, planKey, taskCount = 0, compact = false, onPlanUpdated }) {
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
  const [guidance, setGuidance] = useState('');
  const [syncNotice, setSyncNotice] = useState('');
  const [connect, setConnect] = useState(null);
  const [connectionInfo, setConnectionInfo] = useState(null);
  const [connectionTested, setConnectionTested] = useState(false);
  const [logs, setLogs] = useState([]);
  const [newProject, setNewProject] = useState(null);
  const [destinationMode, setDestinationMode] = useState('');
  const [keyError, setKeyError] = useState('');
  const openedSync = useRef('');
  const summaryLog = lastSyncSummary(logs);

  const applySyncResult = useCallback(async (data) => {
    setBinding((current) => ({ ...(current || {}), ...(data?.result?.binding || data?.binding || {}) }));
    setLogs(data?.logs || []);
    const pulled = Number(data?.result?.pulled || 0);
    const changed = pulled;
    if (changed > 0) {
      try {
        await onPlanUpdated?.({ result: data?.result || {}, data });
        setSyncNotice(`Updated from Jira: ${changed} change${changed === 1 ? '' : 's'}`);
      } catch (refreshError) {
        setError(String(refreshError?.message || refreshError || 'Jira changes were saved, but the plan could not refresh.'));
      }
    }
  }, [onPlanUpdated]);

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
    if (!binding?.id || ['paused', 'reconnect_required', 'links_missing', 'disconnected'].includes(binding.status) || openedSync.current === binding.id) return;
    openedSync.current = binding.id;
    Jaspen.syncPmBinding(binding.id).then(applySyncResult)
      .catch((e) => {
        if (isReconnectError(e)) {
          setConnectionInfo(e?.data?.connection || null);
          setBinding((current) => ({ ...(current || {}), ...(e?.data?.binding || {}), status:'reconnect_required' }));
        }
        setError(friendlyJiraError(e, 'Automatic sync failed. Use Retry.'));
      });
  }, [binding, applySyncResult]);

  const selectedProject = useMemo(() => projects.find((p) => p.key === projectKey), [projects, projectKey]);

  const begin = () => {
    setOpen(true); setTool(''); setConnect(null); setConnectionTested(false);
    setProjects([]); setProjectKey(''); setPreview(null); setError(''); setGuidance('');
    setConnectionInfo(null); setDestinationMode(''); setNewProject(null); setKeyError('');
  };

  const openConnection = (info = connectionInfo, message = '') => {
    setTool('jira'); setOpen(true); setConnect(connectionDraft(info)); setConnectionTested(false);
    setGuidance(message); setError(''); setDestinationMode('');
  };

  const reconnectBinding = async () => {
    setBusy(true);
    try {
      const data = await Jaspen.listJiraProjects();
      openConnection(data?.connection || connectionInfo, RECONNECT_MESSAGE);
    } catch (e) {
      openConnection(e?.data?.connection || connectionInfo, RECONNECT_MESSAGE);
    } finally { setBusy(false); }
  };

  const chooseTool = async (nextTool) => {
    if (nextTool !== 'jira') return;
    setTool(nextTool); setBusy(true); setError(''); setGuidance('');
    try {
      const [projectData, previewData] = await Promise.all([
        Jaspen.listJiraProjects(), Jaspen.previewPmSync(threadId, planKey, true),
      ]);
      setProjects(projectData?.projects || []);
      setConnectionInfo(projectData?.connection || null);
      setDestinationMode((projectData?.projects || []).length ? 'existing' : '');
      if (!(projectData?.projects || []).length) setGuidance('No Jira projects were found. Choose Create new or use a different Jira account.');
      setPreview(previewData?.preview || null);
    } catch (e) {
      const info = e?.data?.connection || null;
      setConnectionInfo(info);
      if (isReconnectError(e)) {
        openConnection(info, RECONNECT_MESSAGE);
      } else if (!info?.has_api_token) {
        openConnection(info, 'Connect Jira to choose or create a project for this execution plan.');
      } else {
        setError(friendlyJiraError(e, 'Jira projects could not be loaded. Try again or use a different account.'));
      }
    } finally { setBusy(false); }
  };

  const testConnection = async () => {
    setBusy(true); setError('');
    try {
      await Jaspen.testJiraConnection(connect);
      setConnectionTested(true);
    } catch (e) { setConnectionTested(false); setError(friendlyJiraError(e, 'Could not connect Jira.')); }
    finally { setBusy(false); }
  };

  const saveConnection = async () => {
    setBusy(true); setError('');
    try {
      if (!connectionTested) throw new Error('Test the connection before saving it.');
      const saved = await Jaspen.connectJira(connect);
      setConnectionInfo({ base_url: saved?.base_url || connect.jira_base_url, email: connect.jira_email, has_api_token: true });
      setConnect(null);
      setGuidance('');
      if (binding) {
        const restored = await Jaspen.updatePmSyncBinding(binding.id, { status:'active' });
        setBinding(restored?.binding || { ...binding, status:'active' });
        setOpen(false);
        openedSync.current = '';
        return;
      }
      const data = await Jaspen.listJiraProjects();
      setProjects(data?.projects || []);
      setConnectionInfo(data?.connection || { base_url: connect.jira_base_url, email: connect.jira_email, has_api_token: true });
      setDestinationMode((data?.projects || []).length ? 'existing' : '');
      const p = await Jaspen.previewPmSync(threadId, planKey, groupEpics);
      setPreview(p?.preview || null);
    } catch (e) { setError(friendlyJiraError(e, 'Could not connect Jira.')); }
    finally { setBusy(false); }
  };

  const createProject = async () => {
    setBusy(true); setError('');
    try {
      const validation = projectKeyError(newProject?.key);
      setKeyError(validation);
      if (validation) throw new Error(validation);
      const data = await Jaspen.createJiraProject(newProject);
      const project = data?.project;
      if (!project?.key) throw new Error('Jira did not return the new project.');
      setProjects((current) => [...current.filter((row) => row.key !== project.key), project]);
      setProjectKey(project.key); setNewProject(null); setDestinationMode('existing');
    } catch (e) {
      if (isReconnectError(e)) openConnection(e?.data?.connection, RECONNECT_MESSAGE);
      else setError(friendlyJiraError(e, 'Could not create the Jira project.'));
    }
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
    setBusy(true); setError(''); setSyncNotice('');
    try {
      const data = await Jaspen.syncPmBinding(binding.id);
      await applySyncResult(data);
      if (data?.result?.errors?.length && data?.result?.binding?.status !== 'links_missing') setError(`${data.result.failed} item(s) failed. Retry will continue from saved links.`);
    } catch (e) {
      if (isReconnectError(e)) {
        setConnectionInfo(e?.data?.connection || null);
        setBinding((current) => ({ ...(current || {}), ...(e?.data?.binding || {}), status:'reconnect_required' }));
      }
      setError(friendlyJiraError(e, 'Sync failed.'));
    }
    finally { setBusy(false); }
  };

  const recreateMissing = async () => {
    setBusy(true); setError(''); setSyncNotice('');
    try {
      const data = await Jaspen.recreateMissingPmLinks(binding.id);
      await applySyncResult(data);
      if (data?.result?.errors?.length) setError(`${data.result.failed} item(s) failed. Retry will continue from saved links.`);
    } catch (e) { setError(friendlyJiraError(e, 'The missing Jira issues could not be recreated.')); }
    finally { setBusy(false); }
  };

  const unlinkPlan = async () => {
    setBusy(true); setError(''); setSyncNotice('');
    try {
      const data = await Jaspen.unlinkPmBinding(binding.id);
      setBinding(data?.binding || { ...binding, status:'disconnected' });
      setLogs(data?.logs || logs);
    } catch (e) { setError(String(e?.data?.error || e?.message || e || 'The plan could not be unlinked.')); }
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

  if (binding && !open) return <div style={{ display: 'inline-flex', alignItems: 'center', gap: 7, flexWrap: 'wrap', maxWidth: compact ? 560 : 'none' }}>
    <div style={{ display:'grid', gap:3 }}>
      <span style={{ ...buttonStyle, cursor: 'default', color: ['error', 'reconnect_required', 'paused', 'links_missing'].includes(binding.status) ? '#b91c1c' : COLOR.greenInk }}>
        ● {bindingStatusLabel(binding.status)}{binding.last_success_at ? ` · ${new Date(binding.last_success_at).toLocaleString()}` : ''}
      </span>
      <span style={{ color:COLOR.ink, fontSize:11.5 }}>Synced by {syncOwnerLabel(binding)} with their Jira account</span>
      {syncWarningMessage(binding) && <span role="alert" style={{ color:'#b91c1c', fontSize:11.5 }}>{syncWarningMessage(binding)}</span>}
    </div>
    {!['links_missing', 'disconnected'].includes(binding.status) && <label style={{ ...buttonStyle, display:'inline-flex', gap:6, alignItems:'center' }}><input type="checkbox" checked={binding.mode === 'two_way'} onChange={(e) => toggleTwoWay(e.target.checked)} />Two-way sync</label>}
    {!['links_missing', 'disconnected'].includes(binding.status) && <button type="button" onClick={syncNow} disabled={busy} style={buttonStyle}>{busy ? 'Syncing…' : 'Sync now'}</button>}
    {binding.status === 'links_missing' && <button type="button" onClick={recreateMissing} disabled={busy} style={{ ...buttonStyle, background:COLOR.rose, borderColor:COLOR.rose, color:'#fff' }}>{busy ? 'Recreating…' : `Recreate in ${binding.external_container_id}`}</button>}
    {binding.status === 'links_missing' && <button type="button" onClick={unlinkPlan} disabled={busy} style={buttonStyle}>Unlink this plan</button>}
    {(binding.status === 'reconnect_required' || binding.pause_reason === 'credential_disconnected') && <button type="button" onClick={reconnectBinding} disabled={busy} style={buttonStyle}>Reconnect Jira</button>}
    {binding.external_container_url && <a href={binding.external_container_url} target="_blank" rel="noreferrer" style={{ ...buttonStyle, textDecoration: 'none' }}>View in Jira</a>}
    {error && <span role="alert" style={{ color: '#b91c1c', fontSize: 11.5 }}>{error}</span>}
    {syncNotice && <span role="status" style={{ color: COLOR.greenInk, fontSize: 11.5 }}>{syncNotice}</span>}
    {summaryLog && <span style={{ color: COLOR.mute, fontSize: 11.5 }}>Last sync: {syncLogStatusLabel(summaryLog.status)} · {summaryLog.items_synced || 0} {summaryLog.items_synced === 1 ? 'change' : 'changes'}{(summaryLog.sync_metadata?.conflicts || []).length ? ` · ${summaryLog.sync_metadata.conflicts.length} need review` : ''}</span>}
    {logs.length > 0 && <details style={{ fontSize:11.5, color:COLOR.ink }}><summary style={{ cursor:'pointer' }}>Sync history</summary><div style={{ position:'absolute', zIndex:20, background:'#fff', border:`1px solid ${COLOR.line}`, borderRadius:8, padding:10, width:330, boxShadow:'0 10px 30px rgba(22,31,59,.12)' }}>{logs.slice(0, 5).map((log) => <div key={log.id} style={{ padding:'5px 0', borderBottom:`1px solid ${COLOR.line2}` }}><strong>{syncLogStatusLabel(log.status)}</strong> · {log.items_synced || 0} changes · {log.created_at ? new Date(log.created_at).toLocaleString() : 'just now'}{(log.sync_metadata?.notes || []).map((note, index) => <div key={`note-${index}`} style={{ color:COLOR.mute }}>{note}</div>)}{(log.sync_metadata?.conflicts || []).map((conflict) => <div key={`${conflict.task_id}-${conflict.field}`} style={{ color:'#9f1239' }}>{conflict.task_id}: choose the {conflict.field} value</div>)}{(log.sync_metadata?.errors || []).map((item, index) => <div key={index} style={{ color:'#9f1239' }}>{item.error}</div>)}</div>)}</div></details>}
  </div>;

  const close = () => { setOpen(false); setTool(''); setConnect(null); setError(''); setGuidance(''); };

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
        {guidance && <div role="status" style={{ padding: 10, borderRadius: 8, background: COLOR.line2, color: COLOR.navy2, fontSize: 12, marginBottom: 14 }}>{guidance}</div>}
        {!tool ? <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:10 }}>
          <Choice checked={false} onClick={() => chooseTool('jira')} title="Jira" detail="Connect an existing project or create a new one" />
          <Choice checked={false} disabled title="Smartsheet" detail="Coming soon" />
        </div> : connect ? <div style={{ display: 'grid', gap: 10 }}>
          <strong style={{ color: COLOR.navy }}>Connect Jira</strong>
          <input aria-label="Jira site URL" style={inputStyle} placeholder="https://company.atlassian.net" value={connect.jira_base_url} onChange={(e) => setConnect({ ...connect, jira_base_url: e.target.value })} />
          <input aria-label="Jira email" style={inputStyle} placeholder="you@company.com" value={connect.jira_email} onChange={(e) => setConnect({ ...connect, jira_email: e.target.value })} />
          <input aria-label="Jira API token" style={inputStyle} type="password" placeholder="API token" value={connect.jira_api_token} onChange={(e) => setConnect({ ...connect, jira_api_token: e.target.value })} />
          <div style={{ color:COLOR.ink, fontSize:12 }}>Create an Atlassian API token, then paste it here. <a href="https://id.atlassian.com/manage-profile/security/api-tokens" target="_blank" rel="noreferrer">Open Atlassian API tokens</a></div>
          <div style={{ display:'flex', gap:8 }}><button type="button" onClick={() => { setTool(''); setConnect(null); setError(''); }} style={buttonStyle}>Back</button><button type="button" onClick={testConnection} disabled={busy || !connect.jira_base_url || !connect.jira_email || !connect.jira_api_token} style={buttonStyle}>{busy ? 'Testing…' : 'Test connection'}</button><button type="button" onClick={saveConnection} disabled={busy || !connectionTested} style={{ ...buttonStyle, border:`1px solid ${connectionTested ? COLOR.rose : COLOR.line}`, background:connectionTested ? COLOR.rose : '#fff', color:connectionTested ? '#fff' : COLOR.mute }}>Save and continue</button></div>
        </div> : <div style={{ display: 'grid', gap: 16 }}>
          {connectionInfo && <div style={{ background:COLOR.line2, borderRadius:8, padding:10, color:COLOR.navy2, fontSize:12 }}>
            Using Jira: {connectionInfo.base_url || 'saved site'} · {connectionInfo.email || 'saved email'} · <button type="button" onClick={() => openConnection(connectionInfo)} style={{ border:0, background:'transparent', color:COLOR.rose, fontWeight:700, cursor:'pointer', padding:0 }}>Use a different account</button>
          </div>}
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:8 }}>
            <Choice checked={destinationMode === 'existing'} disabled={!projects.length} onClick={() => { setDestinationMode('existing'); setNewProject(null); void updatePreview(true); }} title="Choose existing" detail={projects.length ? `${projects.length} project${projects.length === 1 ? '' : 's'} available` : 'No projects available'} />
            <Choice checked={destinationMode === 'create'} onClick={() => { setDestinationMode('create'); setProjectKey(''); setNewProject({ key:'', name:'' }); setKeyError(''); void updatePreview(false); }} title="Create new" detail="Create a Jira project for this plan" />
          </div>
          {destinationMode === 'existing' && projects.length > 0 && <label style={{ display: 'grid', gap: 5, fontSize: 12, color: COLOR.navy, fontWeight: 650 }}>Destination project
            <select aria-label="Destination project" value={projectKey} onChange={(e) => setProjectKey(e.target.value)} style={{ padding: 9, border: `1px solid ${COLOR.line}`, borderRadius: 8 }}><option value="">Choose a Jira project…</option>{projects.map((p) => <option key={p.key} value={p.key}>{p.key} · {p.name}</option>)}</select>
          </label>}
          {destinationMode === 'create' && newProject && <div style={{ display:'grid', gap:8 }}>
            <label style={{ display:'grid', gap:5, fontSize:12, color:COLOR.navy, fontWeight:650 }}>Project name<input style={inputStyle} aria-label="Project name" placeholder="Jaspen Production Test" value={newProject.name} onChange={(e) => { const name=e.target.value; setNewProject({ ...newProject, name, key:suggestedProjectKey(name) }); setKeyError(''); }} /></label>
            <label style={{ display:'grid', gap:5, fontSize:12, color:COLOR.navy, fontWeight:650 }}>Project key (e.g. JPT)<input style={inputStyle} aria-label="Project key (e.g. JPT)" placeholder="JPT" value={newProject.key} onChange={(e) => { const key=e.target.value; setNewProject({ ...newProject, key }); setKeyError(projectKeyError(key)); }} /></label>
            <div style={{ color:keyError ? '#9f1239' : COLOR.mute, fontSize:11.5 }}>{keyError || 'Short code used in issue IDs, e.g. JPT-12'}</div>
            <button type="button" onClick={createProject} disabled={busy || !newProject.key || !newProject.name || Boolean(keyError)} style={buttonStyle}>Create project</button>
          </div>}
          <div style={{ display: 'flex', gap: 14 }}>
            <label style={{ flex: 1, display: 'grid', gap: 5, fontSize: 12, color: COLOR.navy, fontWeight: 650 }}>Issue type<select aria-label="Task issue type" value={issueType} onChange={(e) => setIssueType(e.target.value)} style={{ padding: 9, border: `1px solid ${COLOR.line}`, borderRadius: 8 }}><option>Task</option><option>Story</option></select></label>
            <label style={{ flex: 1, display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: COLOR.navy }}><input type="checkbox" checked={groupEpics} onChange={(e) => updatePreview(e.target.checked)} /> Group tasks under epics</label>
          </div>
          <label style={{ display:'flex', alignItems:'center', gap:8, color:COLOR.navy, fontSize:12, fontWeight:650 }}><input type="checkbox" checked={mode === 'two_way'} onChange={(e) => setMode(e.target.checked ? 'two_way' : 'push_only')} />Two-way sync <span style={{ color:COLOR.mute, fontWeight:400 }}>(on by default; off is push only)</span></label>
          <details><summary style={{ color:COLOR.navy, fontSize:12, fontWeight:700, cursor:'pointer' }}>Advanced conflict handling</summary><div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginTop:8 }}>{POLICIES.map(([value, label]) => <Choice key={value} checked={policy === value} onClick={() => setPolicy(value)} title={label} />)}</div></details>
          {preview && <div style={{ background: COLOR.line2, borderRadius: 9, padding: 12, color: COLOR.navy2, fontSize: 12.5 }}>
            <div>{preview.structure || `Creates ${preview.issues} tasks.`}{selectedProject ? ` Destination: ${selectedProject.key}.` : ''}</div>
            {preview.tasks_without_start_date > 0 && <div style={{ marginTop:6 }}>{preview.tasks_without_start_date} task{preview.tasks_without_start_date === 1 ? '' : 's'} {preview.tasks_without_start_date === 1 ? 'has' : 'have'} no start date and won't appear on Jira's timeline.</div>}
            {preview.unmapped_owners > 0 && <div style={{ marginTop:6 }}>{preview.unmapped_owners} owner{preview.unmapped_owners === 1 ? '' : 's'} will be left unassigned.</div>}
          </div>}
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}><button type="button" onClick={() => { setTool(''); setError(''); }} style={buttonStyle}>Back</button><div style={{ display:'flex', gap:8 }}><button type="button" onClick={close} style={buttonStyle}>Cancel</button><button type="button" onClick={send} disabled={busy || !projectKey} style={{ ...buttonStyle, border:`1px solid ${COLOR.rose}`, background: COLOR.rose, color: '#fff' }}>{busy ? 'Linking…' : 'Link project'}</button></div></div>
        </div>}
      </div>
    </div>}
  </>;
}
