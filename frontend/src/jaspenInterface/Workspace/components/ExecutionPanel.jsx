import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faCalendarAlt,
  faChevronDown,
  faChevronRight,
  faColumns,
  faList,
  faLock,
  faPlus,
  faRefresh,
  faSpinner,
  faTrash,
} from '@fortawesome/free-solid-svg-icons';
import { Jaspen } from '../JaspenClient';
import { ExecutionPanelSkeleton } from '../../../shared/components/SkeletonLoader';
import './ExecutionPanel.css';

const STATUS_ORDER = ['todo', 'in_progress', 'blocked', 'done'];
const STATUS_CONFIG = {
  todo: { label: 'To Do', color: '#6b7280' },
  in_progress: { label: 'In Progress', color: '#2563eb' },
  blocked: { label: 'Blocked', color: '#dc2626' },
  done: { label: 'Done', color: '#16a34a' },
};

const PRIORITY_CONFIG = {
  high: { label: 'High', color: '#dc2626' },
  medium: { label: 'Medium', color: '#d97706' },
  low: { label: 'Low', color: '#6b7280' },
};

function normalizeStatus(value) {
  const key = String(value || '').trim().toLowerCase();
  return STATUS_CONFIG[key] ? key : 'todo';
}

function normalizePriority(value) {
  const key = String(value || '').trim().toLowerCase();
  return PRIORITY_CONFIG[key] ? key : 'medium';
}

function extractPhaseName(raw) {
  if (typeof raw === 'string') {
    const trimmed = raw.trim();
    return trimmed || 'Execution';
  }
  if (raw && typeof raw === 'object') {
    const trimmed = String(raw.name || raw.label || '').trim();
    return trimmed || 'Execution';
  }
  return 'Execution';
}

function formatDateLabel(value) {
  if (!value) return 'No date';
  const parsed = new Date(value);
  if (!Number.isFinite(parsed.getTime())) return 'No date';
  return parsed.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function sortTasks(tasks) {
  return [...tasks].sort((a, b) => {
    const phaseA = extractPhaseName(a?.phase);
    const phaseB = extractPhaseName(b?.phase);
    if (phaseA !== phaseB) return phaseA.localeCompare(phaseB);
    const orderA = Number(a?.order || 0);
    const orderB = Number(b?.order || 0);
    if (orderA !== orderB) return orderA - orderB;
    return String(a?.title || '').localeCompare(String(b?.title || ''));
  });
}

function timelineSegments(tasks) {
  if (!tasks.length) return [];

  const enriched = tasks.map((task, idx) => {
    const estimatedDays = Math.max(1, Number(task?.estimated_days || task?.timeline_days || 1));
    const dueDate = task?.due_date ? new Date(task.due_date) : null;
    const dueTime = dueDate && Number.isFinite(dueDate.getTime()) ? dueDate.getTime() : null;
    const startTime = dueTime != null
      ? dueTime - ((estimatedDays - 1) * 86400000)
      : (Date.now() + (idx * 86400000));
    const endTime = dueTime != null
      ? dueTime
      : (startTime + ((estimatedDays - 1) * 86400000));
    return { task, estimatedDays, startTime, endTime };
  });

  const minStart = Math.min(...enriched.map((item) => item.startTime));
  const maxEnd = Math.max(...enriched.map((item) => item.endTime));
  const span = Math.max(86400000, maxEnd - minStart);

  return enriched.map((item) => ({
    ...item,
    leftPct: ((item.startTime - minStart) / span) * 100,
    widthPct: Math.max(6, ((item.endTime - item.startTime + 86400000) / span) * 100),
  }));
}

function nextStatus(status) {
  const idx = STATUS_ORDER.indexOf(normalizeStatus(status));
  return STATUS_ORDER[Math.min(idx + 1, STATUS_ORDER.length - 1)];
}

function statusSyncLabel(item, selectedConnectorIds) {
  const connected = Boolean(item?.connected);
  if (!connected) return 'Disconnected';
  if (selectedConnectorIds.includes(String(item?.id || ''))) return 'Ready to sync';
  return 'Connected';
}

function threadSyncStatusLabel(status) {
  const key = String(status || '').trim().toLowerCase();
  if (key === 'not_started') return 'No PM tool selected';
  if (key === 'tool_selected' || key === 'wbs_pending') return 'Waiting for execution plan';
  if (key === 'ready') return 'Ready to sync';
  if (key === 'syncing') return 'Syncing…';
  if (key === 'synced') return 'Synced';
  if (key === 'error') return 'Sync error';
  if (key === 'paused') return 'Sync paused';
  if (key === 'degraded') return 'Connector issue';
  return 'Sync status unavailable';
}

function preferredPmToolLabel(toolId) {
  const key = String(toolId || '').trim().toLowerCase();
  if (key === 'jaspen') return 'Jaspen';
  if (key === 'jira_sync') return 'Jira';
  if (key === 'smartsheet_sync') return 'Smartsheet';
  return key;
}

function ownerOptionsFromMembers(members) {
  return (Array.isArray(members) ? members : [])
    .map((member) => {
      const id = String(member?.user_id || member?.user?.id || member?.id || '').trim();
      const name = String(member?.name || member?.user?.name || member?.email || member?.user?.email || '').trim();
      if (!name) return null;
      return {
        id: id || name,
        label: name,
      };
    })
    .filter(Boolean);
}

export default function ExecutionPanel({
  threadId,
  wbs,
  authFetch,
  onRefresh,
  onUpdateTask,
  onAddTask,
  onRemoveTask,
  onAddDependency,
  canEditFields,
  canEditStructure,
  canEditDependencies,
  isViewer,
  isLocked,
  onOpenChat,
  onOpenBilling,
  loading = false,
}) {
  const [view, setView] = useState('list');
  const [expandedPhases, setExpandedPhases] = useState({});
  const [drafts, setDrafts] = useState({});
  const [addingPhase, setAddingPhase] = useState(null);
  const [newTaskTitle, setNewTaskTitle] = useState('');
  const [members, setMembers] = useState([]);
  const [membersLoaded, setMembersLoaded] = useState(false);
  const [syncState, setSyncState] = useState(null);
  const [syncLoading, setSyncLoading] = useState(false);
  const [syncAction, setSyncAction] = useState('');
  const [panelMessage, setPanelMessage] = useState('');

  const tasks = useMemo(() => {
    if (!wbs || !Array.isArray(wbs.tasks)) return [];
    return sortTasks(wbs.tasks);
  }, [wbs]);

  const phases = useMemo(() => {
    const phaseNames = new Set(
      (Array.isArray(wbs?.phases) ? wbs.phases : []).map((phase) => extractPhaseName(phase))
    );
    tasks.forEach((task) => phaseNames.add(extractPhaseName(task?.phase)));
    if (phaseNames.size === 0) phaseNames.add('Execution');
    return [...phaseNames];
  }, [tasks, wbs?.phases]);

  const tasksByPhase = useMemo(() => {
    const grouped = {};
    phases.forEach((phase) => {
      grouped[phase] = [];
    });
    tasks.forEach((task) => {
      const phase = extractPhaseName(task?.phase);
      if (!grouped[phase]) grouped[phase] = [];
      grouped[phase].push(task);
    });
    return grouped;
  }, [phases, tasks]);

  const boardColumns = useMemo(() => {
    const columns = {};
    STATUS_ORDER.forEach((status) => {
      columns[status] = [];
    });
    tasks.forEach((task) => {
      columns[normalizeStatus(task?.status)].push(task);
    });
    return columns;
  }, [tasks]);

  const timelineTasks = useMemo(() => timelineSegments(tasks), [tasks]);
  const ownerOptions = useMemo(() => ownerOptionsFromMembers(members), [members]);
  const selectedConnectorIds = useMemo(() => {
    const connectorIds = syncState?.thread_sync?.connector_ids;
    return Array.isArray(connectorIds) ? connectorIds.map((id) => String(id)) : [];
  }, [syncState]);
  const threadSyncStatus = String(
    syncState?.thread_sync_status || syncState?.thread_sync?.thread_sync_status || ''
  ).trim().toLowerCase();
  const preferredPmTool = String(
    syncState?.preferred_pm_tool || syncState?.thread_sync?.preferred_pm_tool || ''
  ).trim().toLowerCase();
  const syncStatusMessage = String(syncState?.message || '').trim();

  useEffect(() => {
    if (!threadId || typeof authFetch !== 'function') return;
    let cancelled = false;

    authFetch('/api/v1/team/members?page=1&per_page=100')
      .then((response) => response.json().catch(() => ({})))
      .then((payload) => {
        if (cancelled) return;
        const rows = Array.isArray(payload?.members) ? payload.members : [];
        setMembers(rows);
        setMembersLoaded(true);
      })
      .catch(() => {
        if (!cancelled) {
          setMembers([]);
          setMembersLoaded(true);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [authFetch, threadId]);

  const loadSyncState = useCallback(async () => {
    if (!threadId) return;
    setSyncLoading(true);
    try {
      const payload = await Jaspen.getThreadPmSync(threadId);
      setSyncState(payload || null);
      setPanelMessage('');
    } catch (error) {
      setPanelMessage(error?.message || 'Unable to load sync status.');
      setSyncState(null);
    } finally {
      setSyncLoading(false);
    }
  }, [threadId]);

  useEffect(() => {
    loadSyncState();
  }, [loadSyncState]);

  const setDraftValue = useCallback((taskId, field, value) => {
    setDrafts((prev) => ({
      ...prev,
      [taskId]: {
        ...(prev[taskId] || {}),
        [field]: value,
      },
    }));
  }, []);

  const clearDraftField = useCallback((taskId, field) => {
    setDrafts((prev) => {
      const next = { ...(prev || {}) };
      const row = { ...(next[taskId] || {}) };
      delete row[field];
      if (Object.keys(row).length === 0) {
        delete next[taskId];
      } else {
        next[taskId] = row;
      }
      return next;
    });
  }, []);

  const commitTaskField = useCallback(async (taskId, field, value, currentValue) => {
    if (!canEditFields && field !== 'phase') return;
    if (field === 'phase' && !canEditStructure) return;
    const nextValue = value == null ? '' : String(value);
    const prevValue = currentValue == null ? '' : String(currentValue);
    if (nextValue === prevValue) {
      clearDraftField(taskId, field);
      return;
    }
    try {
      await onUpdateTask?.(taskId, { [field]: value });
      clearDraftField(taskId, field);
      setPanelMessage('');
    } catch (error) {
      setPanelMessage(error?.message || 'Unable to update task.');
    }
  }, [canEditFields, canEditStructure, clearDraftField, onUpdateTask]);

  const submitNewTask = useCallback(async (phase) => {
    const title = String(newTaskTitle || '').trim();
    if (!title) return;
    try {
      await onAddTask?.({
        title,
        phase,
      });
      setNewTaskTitle('');
      setAddingPhase(null);
      setPanelMessage('');
      await onRefresh?.();
    } catch (error) {
      setPanelMessage(error?.message || 'Unable to add task.');
    }
  }, [newTaskTitle, onAddTask, onRefresh]);

  const removeTask = useCallback(async (taskId) => {
    try {
      await onRemoveTask?.(taskId);
      setPanelMessage('');
      await onRefresh?.();
    } catch (error) {
      setPanelMessage(error?.message || 'Unable to remove task.');
    }
  }, [onRefresh, onRemoveTask]);

  const runManualSync = useCallback(async (connectorId) => {
    if (!threadId) return;
    setSyncAction(connectorId);
    try {
      if (connectorId === 'jira_sync') {
        await Jaspen.syncThreadWbsToJira(threadId);
      } else if (connectorId === 'smartsheet_sync') {
        await Jaspen.syncThreadWbsToSmartsheet(threadId);
      }
      await Promise.all([onRefresh?.(), loadSyncState()]);
      setPanelMessage('');
    } catch (error) {
      const code = String(error?.data?.code || '').trim().toUpperCase();
      if (code === 'WBS_NOT_FOUND') {
        setPanelMessage('Execution plan not generated yet. Generate the WBS first, then sync.');
      } else if (code === 'NO_PM_TOOL_SELECTED') {
        setPanelMessage('No PM tool is selected for this thread yet.');
      } else if (code === 'PM_TOOL_NOT_CONNECTED' || code === 'CONNECTOR_NOT_CONNECTED') {
        setPanelMessage('Preferred PM connector is not connected. Re-verify it in Data Sources.');
      } else if (code === 'SYNC_IN_PROGRESS') {
        setPanelMessage('A sync is already in progress. Please wait a moment and retry.');
      } else {
        setPanelMessage(error?.message || 'Unable to sync execution plan.');
      }
    } finally {
      setSyncAction('');
    }
  }, [loadSyncState, onRefresh, threadId]);

  const togglePhase = useCallback((phase) => {
    setExpandedPhases((prev) => ({
      ...prev,
      [phase]: prev[phase] === false,
    }));
  }, []);

  const renderOwnerField = (task) => {
    const draftValue = drafts?.[task.id]?.owner;
    const value = draftValue != null ? draftValue : String(task?.owner || '');
    if (membersLoaded && ownerOptions.length > 0) {
      return (
        <select
          value={value}
          disabled={!canEditFields}
          onChange={(event) => {
            const nextValue = event.target.value;
            setDraftValue(task.id, 'owner', nextValue);
            commitTaskField(task.id, 'owner', nextValue, task?.owner || '');
          }}
        >
          <option value="">Unassigned</option>
          {ownerOptions.map((option) => (
            <option key={option.id} value={option.label}>{option.label}</option>
          ))}
        </select>
      );
    }
    return (
      <input
        type="text"
        value={value}
        disabled={!canEditFields}
        placeholder="Owner"
        onChange={(event) => setDraftValue(task.id, 'owner', event.target.value)}
        onBlur={(event) => commitTaskField(task.id, 'owner', event.target.value, task?.owner || '')}
      />
    );
  };

  const renderListView = () => (
    <div className="execution-phase-stack">
      {phases.map((phase) => {
        const items = tasksByPhase[phase] || [];
        const expanded = expandedPhases[phase] !== false;
        return (
          <section key={phase} className="execution-phase-card">
            <button
              type="button"
              className="execution-phase-toggle"
              onClick={() => togglePhase(phase)}
            >
              <span className="execution-phase-toggle-icon">
                <FontAwesomeIcon icon={expanded ? faChevronDown : faChevronRight} />
              </span>
              <span className="execution-phase-name">{phase}</span>
              <span className="execution-phase-count">{items.length}</span>
            </button>

            {expanded && (
              <div className="execution-phase-body">
                {items.length === 0 && (
                  <div className="execution-phase-empty">No tasks in this phase yet.</div>
                )}
                {items.map((task) => {
                  const status = normalizeStatus(task?.status);
                  const priority = normalizePriority(task?.priority);
                  const draftTitle = drafts?.[task.id]?.title;
                  const titleValue = draftTitle != null ? draftTitle : String(task?.title || '');
                  const draftDueDate = drafts?.[task.id]?.due_date;
                  const dueDateValue = draftDueDate != null ? draftDueDate : String(task?.due_date || '');
                  const draftStatus = drafts?.[task.id]?.status;
                  const statusValue = draftStatus != null ? draftStatus : status;
                  const draftPhase = drafts?.[task.id]?.phase;
                  const phaseValue = draftPhase != null ? draftPhase : extractPhaseName(task?.phase);

                  return (
                    <article key={task.id} className="execution-task-row">
                      <div className="execution-task-row-main">
                        <select
                          value={statusValue}
                          disabled={!canEditFields}
                          className="execution-status-select"
                          onChange={(event) => {
                            const nextValue = event.target.value;
                            setDraftValue(task.id, 'status', nextValue);
                            commitTaskField(task.id, 'status', nextValue, status);
                          }}
                        >
                          {STATUS_ORDER.map((value) => (
                            <option key={value} value={value}>{STATUS_CONFIG[value].label}</option>
                          ))}
                        </select>
                        <input
                          type="text"
                          value={titleValue}
                          className="execution-task-title"
                          disabled={!canEditFields}
                          onChange={(event) => setDraftValue(task.id, 'title', event.target.value)}
                          onBlur={(event) => commitTaskField(task.id, 'title', event.target.value, task?.title || '')}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              event.preventDefault();
                              event.currentTarget.blur();
                            }
                          }}
                        />
                        <span
                          className="execution-priority-pill"
                          style={{ '--execution-priority-color': PRIORITY_CONFIG[priority].color }}
                        >
                          {PRIORITY_CONFIG[priority].label}
                        </span>
                      </div>

                      <div className="execution-task-row-fields">
                        <label>
                          <span>Owner</span>
                          {renderOwnerField(task)}
                        </label>
                        <label>
                          <span>Due date</span>
                          <input
                            type="date"
                            value={dueDateValue ? String(dueDateValue).slice(0, 10) : ''}
                            disabled={!canEditFields}
                            onChange={(event) => {
                              const nextValue = event.target.value || null;
                              setDraftValue(task.id, 'due_date', nextValue);
                              commitTaskField(task.id, 'due_date', nextValue, task?.due_date || '');
                            }}
                          />
                        </label>
                        <label>
                          <span>Phase</span>
                          <select
                            value={phaseValue}
                            disabled={!canEditStructure}
                            onChange={(event) => {
                              const nextValue = event.target.value;
                              setDraftValue(task.id, 'phase', nextValue);
                              commitTaskField(task.id, 'phase', nextValue, extractPhaseName(task?.phase));
                            }}
                          >
                            {phases.map((option) => (
                              <option key={option} value={option}>{option}</option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span>Depends on</span>
                          <select
                            value=""
                            disabled={!canEditDependencies}
                            onChange={(event) => {
                              const dependsOnId = event.target.value;
                              if (!dependsOnId) return;
                              onAddDependency?.(task.id, dependsOnId);
                              event.target.value = '';
                            }}
                          >
                            <option value="">Add dependency…</option>
                            {tasks
                              .filter((candidate) => candidate.id !== task.id && !(Array.isArray(task?.depends_on) && task.depends_on.includes(candidate.id)))
                              .map((candidate) => (
                                <option key={candidate.id} value={candidate.id}>{candidate.title}</option>
                              ))}
                          </select>
                        </label>
                        <div className="execution-task-row-actions">
                          <span className="execution-task-deps">
                            {Array.isArray(task?.depends_on) && task.depends_on.length > 0
                              ? `${task.depends_on.length} dep`
                              : 'No deps'}
                          </span>
                          {canEditStructure && (
                            <button
                              type="button"
                              className="execution-icon-btn danger"
                              onClick={() => removeTask(task.id)}
                              title="Remove task"
                            >
                              <FontAwesomeIcon icon={faTrash} />
                            </button>
                          )}
                        </div>
                      </div>
                    </article>
                  );
                })}

                {canEditStructure && (
                  <div className="execution-add-row">
                    {addingPhase === phase ? (
                      <>
                        <input
                          type="text"
                          value={newTaskTitle}
                          placeholder={`Add a task to ${phase}`}
                          onChange={(event) => setNewTaskTitle(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === 'Enter') {
                              event.preventDefault();
                              submitNewTask(phase);
                            }
                          }}
                        />
                        <button type="button" className="execution-secondary-btn" onClick={() => submitNewTask(phase)}>
                          Save
                        </button>
                        <button type="button" className="execution-tertiary-btn" onClick={() => { setAddingPhase(null); setNewTaskTitle(''); }}>
                          Cancel
                        </button>
                      </>
                    ) : (
                      <button type="button" className="execution-secondary-btn" onClick={() => setAddingPhase(phase)}>
                        <FontAwesomeIcon icon={faPlus} />
                        Add task
                      </button>
                    )}
                  </div>
                )}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );

  const renderBoardView = () => (
    <div className="execution-board">
      {STATUS_ORDER.map((status) => (
        <section key={status} className="execution-board-column">
          <header className="execution-board-column-header">
            <span>{STATUS_CONFIG[status].label}</span>
            <span>{boardColumns[status].length}</span>
          </header>
          <div className="execution-board-column-body">
            {boardColumns[status].map((task) => (
              <article key={task.id} className="execution-board-card">
                <div className="execution-board-card-top">
                  <strong>{task?.title || 'Untitled task'}</strong>
                  <span
                    className="execution-priority-pill"
                    style={{ '--execution-priority-color': PRIORITY_CONFIG[normalizePriority(task?.priority)].color }}
                  >
                    {PRIORITY_CONFIG[normalizePriority(task?.priority)].label}
                  </span>
                </div>
                <div className="execution-board-meta">
                  <span>{extractPhaseName(task?.phase)}</span>
                  <span>{task?.owner || 'Unassigned'}</span>
                  <span>{formatDateLabel(task?.due_date)}</span>
                </div>
                {canEditFields && status !== 'done' && (
                  <button
                    type="button"
                    className="execution-secondary-btn"
                    onClick={() => commitTaskField(task.id, 'status', nextStatus(status), status)}
                  >
                    Move to {STATUS_CONFIG[nextStatus(status)].label}
                  </button>
                )}
              </article>
            ))}
            {boardColumns[status].length === 0 && (
              <div className="execution-board-empty">No tasks</div>
            )}
          </div>
        </section>
      ))}
    </div>
  );

  const renderTimelineView = () => (
    <div className="execution-timeline">
      <div className="execution-timeline-rail" />
      {timelineTasks.map((item) => (
        <div key={item.task.id} className="execution-timeline-row">
          <div className="execution-timeline-meta">
            <strong>{item.task?.title || 'Untitled task'}</strong>
            <span>{extractPhaseName(item.task?.phase)} • {formatDateLabel(item.task?.due_date)}</span>
          </div>
          <div className="execution-timeline-bar-wrap">
            <div
              className={`execution-timeline-bar is-${normalizeStatus(item.task?.status)}`}
              style={{ left: `${item.leftPct}%`, width: `${item.widthPct}%` }}
            >
              {item.estimatedDays}d
            </div>
          </div>
        </div>
      ))}
    </div>
  );

  if (isLocked) {
    return (
      <div className="execution-panel execution-panel-locked">
        <div className="execution-empty-state">
          <div className="execution-empty-icon">
            <FontAwesomeIcon icon={faLock} />
          </div>
          <h3>Execution is available on Essential and above.</h3>
          <p>Upgrade to unlock the execution plan, task board, timeline, and PM sync controls.</p>
          <button type="button" className="execution-primary-btn" onClick={onOpenBilling}>
            Open plans & billing
          </button>
        </div>
      </div>
    );
  }

  if (loading) {
    return <ExecutionPanelSkeleton />;
  }

  if (!tasks.length) {
    return (
      <div className="execution-panel">
        <header className="execution-panel-header">
          <div>
            <p className="execution-eyebrow">Execution</p>
            <h3>Build the plan from strategy</h3>
            <p className="execution-panel-subcopy">Turn the current score into a working execution plan with tasks, owners, and milestones.</p>
          </div>
        </header>

        <div className="execution-empty-state">
          <div className="execution-empty-icon">
            <FontAwesomeIcon icon={faList} />
          </div>
          <h3>No execution plan yet.</h3>
          <p>Ask Jaspen to build one from the current scorecard, then review it here in list, board, or timeline view.</p>
          <div className="execution-empty-actions">
            <button type="button" className="execution-primary-btn" onClick={onOpenChat}>
              Ask Jaspen to build the plan
            </button>
            <button type="button" className="execution-tertiary-btn" onClick={onRefresh}>
              Refresh
            </button>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="execution-panel">
      <header className="execution-panel-header">
        <div>
          <p className="execution-eyebrow">Execution</p>
          <h3>{wbs?.name || 'Execution Plan'}</h3>
          <p className="execution-panel-subcopy">
            Jaspen built this plan from your scorecard context. Update task owners, due dates, statuses, and dependencies as the work progresses.
          </p>
        </div>
        <div className="execution-header-actions">
          <div className="execution-view-toggle" role="tablist" aria-label="Execution views">
            <button type="button" className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>
              <FontAwesomeIcon icon={faList} />
              List
            </button>
            <button type="button" className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>
              <FontAwesomeIcon icon={faColumns} />
              Board
            </button>
            <button type="button" className={view === 'timeline' ? 'active' : ''} onClick={() => setView('timeline')}>
              <FontAwesomeIcon icon={faCalendarAlt} />
              Timeline
            </button>
          </div>
          <button type="button" className="execution-tertiary-btn" onClick={onRefresh}>
            Refresh Plan
          </button>
        </div>
      </header>

      <section className="execution-sync-strip">
        <div className="execution-sync-strip-head">
          <div>
            <p className="execution-eyebrow">Execution Sync</p>
            <h4>Connected PM systems</h4>
            <p className="execution-panel-subcopy">
              {syncStatusMessage || threadSyncStatusLabel(threadSyncStatus)}
              {preferredPmTool ? ` · Preferred tool: ${preferredPmToolLabel(preferredPmTool)}` : ''}
            </p>
          </div>
          <button type="button" className="execution-tertiary-btn" onClick={loadSyncState} disabled={syncLoading} aria-disabled={syncLoading}>
            <FontAwesomeIcon icon={syncLoading ? faSpinner : faRefresh} spin={syncLoading} />
            Refresh
          </button>
        </div>
        <div className="execution-sync-grid">
          {(syncState?.execution_connectors || []).map((connector) => {
            const connectorId = String(connector?.id || '');
            const connected = Boolean(connector?.connected);
            const selected = selectedConnectorIds.includes(connectorId);
            return (
              <article key={connectorId} className={`execution-sync-card ${connected ? 'is-connected' : 'is-disconnected'} ${selected ? 'is-selected' : ''}`}>
                <div className="execution-sync-card-top">
                  <strong>{connector?.label || connectorId}</strong>
                  <span>{statusSyncLabel(connector, selectedConnectorIds)}</span>
                </div>
                <p>{connector?.description || 'Execution sync connector'}</p>
                <div className="execution-sync-card-meta">
                  <span>{connector?.health_status || 'unknown'}</span>
                  <span>{connector?.last_sync_at ? formatDateLabel(connector.last_sync_at) : 'Never synced'}</span>
                </div>
                {connected && canEditStructure && (
                  <button
                    type="button"
                    className="execution-secondary-btn"
                    onClick={() => runManualSync(connectorId)}
                    disabled={syncAction === connectorId} aria-disabled={syncAction === connectorId}
                  >
                    <FontAwesomeIcon icon={syncAction === connectorId ? faSpinner : faRefresh} spin={syncAction === connectorId} />
                    Sync now
                  </button>
                )}
              </article>
            );
          })}
        </div>
      </section>

      {panelMessage && <div className="execution-inline-message">{panelMessage}</div>}
      {isViewer && (
        <div className="execution-inline-note">
          You are viewing this execution plan in read-only mode.
        </div>
      )}

      {view === 'list' && renderListView()}
      {view === 'board' && renderBoardView()}
      {view === 'timeline' && renderTimelineView()}
    </div>
  );
}
