# Comprehensive PM Wiring Instructions: WBS Visualization, Chat-Driven Execution & Role-Gated PM

## What Exists Today

### Backend (fully functional)
- **WBS CRUD:** `GET/PUT /api/v1/strategy/threads/{threadId}/wbs` — read and write full WBS
- **AI WBS generation:** `POST /api/v1/strategy/threads/{threadId}/ai-wbs` — generates WBS from scorecard with Claude, falls back to heuristic
- **AI agent tools:** `update_wbs_task`, `add_wbs_task`, `remove_wbs_task` — chat-driven mutations with plan enforcement
- **External sync:** Jira, Workfront, Smartsheet — bidirectional with webhooks, field mapping, conflict policies
- **Tool registry:** Plan-gated limits (Essential: 75 tasks/150 deps, Team: 300/1000, Enterprise: unlimited)
- **Task model:** id, title, description, status (todo/in_progress/blocked/done), priority (high/medium/low), owner, suggested_role, due_date, timeline_days, estimated_days, order, phase, depends_on[], rationale, risk_area, external_refs

### Frontend (foundation only)
- **WBS state exists** but is never displayed: `threadWbs` state (line 414 of JaspenWorkspace.jsx) is set by `refreshThreadWbs()` (line 650) and updated on mutations (line 755-759) — but no UI reads it
- **Chat action handlers work:** `WBS_ADD_TASK`, `WBS_UPDATE_TASK`, `WBS_ADD_DEPENDENCY` all fetch current WBS, mutate, upsert back, show toast
- **Missing `WBS_REMOVE_TASK`:** Backend has `remove_wbs_task` tool and the mutation refresh detects it (line 730), but there is no `ChatActionTypes.WBS_REMOVE_TASK` handler in the frontend
- **Three tabs exist:** Score, Scenarios, Refine & Rescore — no PM/WBS tab
- **Context budget:** Team/Enterprise plans include `include_active_scenario_and_wbs_snapshot: true` in AI context (tool_registry.py line 22-23), meaning the chat agent sees the current WBS when advising

### What's missing to be PM-competitive
1. No visual WBS — users cannot see their tasks, statuses, dependencies, or timeline
2. No way to directly edit WBS from a UI surface (only through chat)
3. No Gantt/timeline view
4. No Kanban board
5. No milestone tracking
6. No critical path visualization
7. No resource/owner assignment view
8. No progress dashboard
9. Chat agent cannot remove tasks from frontend (missing handler)
10. Chat agent cannot reorder tasks or move between phases

---

## Architecture Decision: Chat-First PM with Visual Feedback

Jaspen's competitive advantage is not being another Jira clone — it's the **AI agent that builds and maintains the execution plan from the strategic analysis**. The sidebar chat should remain the primary interaction model. But users need to **see** what the agent built and **directly edit** when it's faster than asking.

### Design principle
- The chat agent generates and modifies the WBS
- The UI visualizes the current WBS state in real-time
- Users can directly edit tasks from the UI (quick edits) and the WBS state syncs
- Complex restructuring (rephase, bulk dependency changes, regeneration) goes through chat
- The WBS tab refreshes automatically when the agent makes mutations

---

## Step 1: Add WBS_REMOVE_TASK handler

### File: `/frontend/src/shared/hooks/useChatCommands.js`

Add to `ChatActionTypes`:
```javascript
WBS_REMOVE_TASK: 'WBS_REMOVE_TASK',
```

### File: `/frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`

Add handler after the `WBS_ADD_DEPENDENCY` handler (after line ~4081):

```javascript
[ChatActionTypes.WBS_REMOVE_TASK]: async (payload) => {
  if (!canUseWbsWrite) {
    showToast('WBS write tools require Essential or higher.', 'info');
    setBillingModalOpen(true);
    return;
  }
  const tid = currentSessionId || sessionId;
  if (!tid) {
    showToast('Start a thread before updating WBS.', 'error');
    return;
  }

  const taskId = String(payload?.id || payload?.task_id || '').trim();
  if (!taskId) {
    showToast('Task id is required.', 'error');
    return;
  }

  try {
    const wbsResp = await Jaspen.getThreadWbs(tid);
    const currentWbs = (wbsResp?.project_wbs && typeof wbsResp.project_wbs === 'object')
      ? wbsResp.project_wbs
      : { name: 'Execution WBS', tasks: [] };
    let tasks = Array.isArray(currentWbs.tasks) ? [...currentWbs.tasks] : [];

    const beforeCount = tasks.length;
    tasks = tasks.filter((t) => String(t?.id || '') !== taskId);
    if (tasks.length === beforeCount) {
      showToast('Task not found in WBS', 'error');
      return;
    }

    // Clean up dangling dependencies
    tasks = tasks.map((t) => ({
      ...t,
      depends_on: Array.isArray(t.depends_on)
        ? t.depends_on.filter((dep) => dep !== taskId)
        : [],
    }));

    await Jaspen.upsertThreadWbs(tid, { ...currentWbs, tasks });
    showToast('Task removed from WBS', 'success');
  } catch (e) {
    console.error('[WBS_REMOVE_TASK] failed', e);
    if (e?.status === 403) setBillingModalOpen(true);
    showToast(e?.message || 'Failed to remove task', 'error');
  }
},
```

---

## Step 2: Make threadWbs readable and add the Execution tab

### File: `/frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`

### 2a. Fix the unused threadWbs state

Currently line 414 is:
```javascript
const [, setThreadWbs] = useState(null);
```

Change to:
```javascript
const [threadWbs, setThreadWbs] = useState(null);
```

This makes the WBS data available to the render tree.

### 2b. Add the fourth tab

Find the tab rendering area (around line ~4973 where `TabButton` is used). Currently there are three tabs:

```jsx
<TabButton id="summary" label="Score" />
<TabButton id="scenario" label="Scenarios" />
<TabButton id="chat" label="Refine & Rescore" />
```

Add after Scenarios:

```jsx
<TabButton id="summary" label="Score" />
<TabButton id="scenario" label="Scenarios" />
<TabButton id="execution" label="Execution" />
<TabButton id="chat" label="Refine & Rescore" />
```

### 2c. Gate the Execution tab

The execution tab follows the same pattern as Scenarios — Essential+ plan required for write, but read is available to all authenticated users with a thread:

```javascript
const executionTabLocked = effectiveIsViewer && planCategory === 'individual';
```

In the `TabButton` onClick, add handling for the execution tab:
```javascript
if (id === 'execution') {
  setActiveTab(id);
  setView('execution');
  // Refresh WBS when opening tab
  const tid = sessionId || currentSessionId;
  if (tid) refreshThreadWbs(tid);
  return;
}
```

### 2d. Render the Execution tab content

In the tab content area (where `activeTab === 'summary'` etc. are checked), add:

```jsx
{activeTab === 'execution' && (
  <ExecutionPanel
    wbs={threadWbs}
    onRefresh={() => {
      const tid = sessionId || currentSessionId;
      if (tid) refreshThreadWbs(tid);
    }}
    onUpdateTask={async (taskId, updates) => {
      chatCommandHandlers[ChatActionTypes.WBS_UPDATE_TASK]({
        id: taskId,
        ...updates,
      });
    }}
    onAddTask={async (taskData) => {
      chatCommandHandlers[ChatActionTypes.WBS_ADD_TASK](taskData);
    }}
    onRemoveTask={async (taskId) => {
      chatCommandHandlers[ChatActionTypes.WBS_REMOVE_TASK]({ id: taskId });
    }}
    onAddDependency={async (taskId, dependsOnId) => {
      chatCommandHandlers[ChatActionTypes.WBS_ADD_DEPENDENCY]({
        task_id: taskId,
        depends_on: dependsOnId,
      });
    }}
    canWrite={canUseWbsWrite && !effectiveIsViewer}
    isViewer={effectiveIsViewer}
    onOpenChat={() => { setActiveTab('chat'); setView('intake'); }}
    onOpenBilling={() => setBillingModalOpen(true)}
  />
)}
```

---

## Step 3: Create the ExecutionPanel component

### Create: `/frontend/src/jaspenInterface/Workspace/components/ExecutionPanel.jsx`

This is the core PM visual surface. It has three views toggled by internal tabs: **List**, **Board**, and **Timeline**.

### Component structure

```jsx
import React, { useState, useMemo } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faList, faColumns, faCalendarAlt, faPlus, faTrash,
  faChevronDown, faChevronRight, faLink, faExclamationTriangle,
  faCheckCircle, faSpinner, faBan, faCircle, faLock,
} from '@fortawesome/free-solid-svg-icons';
import './ExecutionPanel.css';

const STATUS_CONFIG = {
  todo:        { label: 'To Do',       icon: faCircle,              color: '#6b7280' },
  in_progress: { label: 'In Progress', icon: faSpinner,             color: '#3b82f6' },
  blocked:     { label: 'Blocked',     icon: faBan,                 color: '#ef4444' },
  done:        { label: 'Done',        icon: faCheckCircle,         color: '#22c55e' },
};

const PRIORITY_CONFIG = {
  high:   { label: 'High',   color: '#ef4444' },
  medium: { label: 'Medium', color: '#f59e0b' },
  low:    { label: 'Low',    color: '#6b7280' },
};

export default function ExecutionPanel({
  wbs,
  onRefresh,
  onUpdateTask,
  onAddTask,
  onRemoveTask,
  onAddDependency,
  canWrite,
  isViewer,
  onOpenChat,
  onOpenBilling,
}) {
  const [view, setView] = useState('list'); // 'list' | 'board' | 'timeline'
  const [expandedPhases, setExpandedPhases] = useState({});
  const [addingTask, setAddingTask] = useState(null); // phase name or null
  const [newTaskTitle, setNewTaskTitle] = useState('');

  const tasks = useMemo(() => {
    if (!wbs || !Array.isArray(wbs.tasks)) return [];
    return wbs.tasks;
  }, [wbs]);

  const phases = useMemo(() => {
    const phaseMap = new Map();
    tasks.forEach((task) => {
      const phase = task.phase || 'Unassigned';
      if (!phaseMap.has(phase)) phaseMap.set(phase, []);
      phaseMap.get(phase).push(task);
    });
    // Sort tasks within each phase by order field
    phaseMap.forEach((phaseTasks) => {
      phaseTasks.sort((a, b) => (a.order || 0) - (b.order || 0));
    });
    return phaseMap;
  }, [tasks]);

  const stats = useMemo(() => {
    const total = tasks.length;
    const done = tasks.filter((t) => t.status === 'done').length;
    const blocked = tasks.filter((t) => t.status === 'blocked').length;
    const inProgress = tasks.filter((t) => t.status === 'in_progress').length;
    const todo = total - done - blocked - inProgress;
    const percent = total > 0 ? Math.round((done / total) * 100) : 0;
    return { total, done, blocked, inProgress, todo, percent };
  }, [tasks]);

  // ... render methods below
}
```

### Empty state (no WBS yet)

When `!wbs || tasks.length === 0`:

```jsx
<div className="jas-exec-empty">
  <h3>No execution plan yet</h3>
  <p>
    Complete your analysis and ask Jaspen to generate an execution plan,
    or add tasks manually.
  </p>
  <div className="jas-exec-empty-actions">
    <button onClick={onOpenChat} className="jas-exec-btn-primary">
      Ask Jaspen to build a plan
    </button>
    {canWrite && (
      <button onClick={() => setAddingTask('General')} className="jas-exec-btn-secondary">
        <FontAwesomeIcon icon={faPlus} /> Add task manually
      </button>
    )}
  </div>
</div>
```

### Progress summary bar

Always visible when tasks exist:

```jsx
<div className="jas-exec-progress">
  <div className="jas-exec-progress-bar">
    <div className="jas-exec-progress-fill" style={{ width: `${stats.percent}%` }} />
  </div>
  <div className="jas-exec-progress-stats">
    <span>{stats.percent}% complete</span>
    <span>{stats.done}/{stats.total} tasks done</span>
    {stats.blocked > 0 && (
      <span className="jas-exec-stat-blocked">
        <FontAwesomeIcon icon={faExclamationTriangle} /> {stats.blocked} blocked
      </span>
    )}
  </div>
</div>
```

### View toggle

```jsx
<div className="jas-exec-view-toggle">
  <button className={view === 'list' ? 'active' : ''} onClick={() => setView('list')}>
    <FontAwesomeIcon icon={faList} /> List
  </button>
  <button className={view === 'board' ? 'active' : ''} onClick={() => setView('board')}>
    <FontAwesomeIcon icon={faColumns} /> Board
  </button>
  <button className={view === 'timeline' ? 'active' : ''} onClick={() => setView('timeline')}>
    <FontAwesomeIcon icon={faCalendarAlt} /> Timeline
  </button>
</div>
```

---

## Step 4: List View (default — like Smartsheet/Jira list)

The List view groups tasks by phase with collapsible sections. Each task row shows: status indicator, title (inline editable), priority badge, owner, due date, estimated days, dependency count, and actions.

### Task row structure

```jsx
const TaskRow = ({ task }) => {
  const statusCfg = STATUS_CONFIG[task.status] || STATUS_CONFIG.todo;
  const priorityCfg = PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.medium;
  const depCount = Array.isArray(task.depends_on) ? task.depends_on.length : 0;

  return (
    <div className="jas-exec-task-row">
      {/* Status dropdown */}
      {canWrite ? (
        <select
          className="jas-exec-status-select"
          value={task.status || 'todo'}
          onChange={(e) => onUpdateTask(task.id, { status: e.target.value })}
          style={{ color: statusCfg.color }}
        >
          {Object.entries(STATUS_CONFIG).map(([key, cfg]) => (
            <option key={key} value={key}>{cfg.label}</option>
          ))}
        </select>
      ) : (
        <span className="jas-exec-status-badge" style={{ color: statusCfg.color }}>
          <FontAwesomeIcon icon={statusCfg.icon} /> {statusCfg.label}
        </span>
      )}

      {/* Title — inline editable */}
      <span
        className={`jas-exec-task-title ${canWrite ? 'editable' : ''}`}
        contentEditable={canWrite}
        suppressContentEditableWarning
        onBlur={(e) => {
          const newTitle = e.target.textContent.trim();
          if (newTitle && newTitle !== task.title) {
            onUpdateTask(task.id, { title: newTitle });
          }
        }}
      >
        {task.title}
      </span>

      {/* Priority badge */}
      <span className="jas-exec-priority" style={{ color: priorityCfg.color }}>
        {priorityCfg.label}
      </span>

      {/* Owner */}
      {canWrite ? (
        <input
          className="jas-exec-owner-input"
          placeholder="Unassigned"
          defaultValue={task.owner || ''}
          onBlur={(e) => {
            const val = e.target.value.trim();
            if (val !== (task.owner || '')) onUpdateTask(task.id, { owner: val });
          }}
        />
      ) : (
        <span className="jas-exec-owner">{task.owner || 'Unassigned'}</span>
      )}

      {/* Due date */}
      {canWrite ? (
        <input
          type="date"
          className="jas-exec-date-input"
          defaultValue={task.due_date || ''}
          onChange={(e) => onUpdateTask(task.id, { due_date: e.target.value || null })}
        />
      ) : (
        <span className="jas-exec-date">{task.due_date || '—'}</span>
      )}

      {/* Estimated days */}
      <span className="jas-exec-est">{task.estimated_days || task.timeline_days || '—'}d</span>

      {/* Dependencies indicator */}
      {depCount > 0 && (
        <span className="jas-exec-deps" title={`Depends on ${depCount} task(s)`}>
          <FontAwesomeIcon icon={faLink} /> {depCount}
        </span>
      )}

      {/* Remove button */}
      {canWrite && (
        <button
          className="jas-exec-remove-btn"
          title="Remove task"
          onClick={() => {
            if (window.confirm(`Remove "${task.title}"?`)) {
              onRemoveTask(task.id);
            }
          }}
        >
          <FontAwesomeIcon icon={faTrash} />
        </button>
      )}
    </div>
  );
};
```

### Phase grouping

```jsx
const PhaseGroup = ({ phaseName, phaseTasks }) => {
  const isExpanded = expandedPhases[phaseName] !== false; // default expanded

  return (
    <div className="jas-exec-phase">
      <button
        className="jas-exec-phase-header"
        onClick={() => setExpandedPhases((prev) => ({ ...prev, [phaseName]: !isExpanded }))}
      >
        <FontAwesomeIcon icon={isExpanded ? faChevronDown : faChevronRight} />
        <span className="jas-exec-phase-name">{phaseName}</span>
        <span className="jas-exec-phase-count">{phaseTasks.length} tasks</span>
        <span className="jas-exec-phase-done">
          {phaseTasks.filter((t) => t.status === 'done').length} done
        </span>
      </button>

      {isExpanded && (
        <div className="jas-exec-phase-tasks">
          {phaseTasks.map((task) => (
            <TaskRow key={task.id} task={task} />
          ))}

          {/* Inline add task for this phase */}
          {canWrite && addingTask === phaseName && (
            <div className="jas-exec-add-row">
              <input
                autoFocus
                placeholder="Task title..."
                value={newTaskTitle}
                onChange={(e) => setNewTaskTitle(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && newTaskTitle.trim()) {
                    onAddTask({ phase_name: phaseName, title: newTaskTitle.trim(), priority: 'medium' });
                    setNewTaskTitle('');
                    setAddingTask(null);
                  }
                  if (e.key === 'Escape') {
                    setNewTaskTitle('');
                    setAddingTask(null);
                  }
                }}
              />
            </div>
          )}

          {canWrite && addingTask !== phaseName && (
            <button
              className="jas-exec-add-task-btn"
              onClick={() => { setAddingTask(phaseName); setNewTaskTitle(''); }}
            >
              <FontAwesomeIcon icon={faPlus} /> Add task
            </button>
          )}
        </div>
      )}
    </div>
  );
};
```

---

## Step 5: Board View (Kanban — like Jira/Trello)

The Board view groups tasks by status column. Each column is one of the four statuses. Cards are draggable between columns (or click-to-move for simplicity in Phase 1).

```jsx
const BoardView = () => {
  const columns = Object.entries(STATUS_CONFIG);
  const tasksByStatus = useMemo(() => {
    const grouped = {};
    Object.keys(STATUS_CONFIG).forEach((s) => { grouped[s] = []; });
    tasks.forEach((t) => {
      const status = t.status || 'todo';
      if (grouped[status]) grouped[status].push(t);
      else grouped.todo.push(t);
    });
    return grouped;
  }, [tasks]);

  return (
    <div className="jas-exec-board">
      {columns.map(([status, cfg]) => (
        <div key={status} className="jas-exec-board-column">
          <div className="jas-exec-board-column-header" style={{ borderTopColor: cfg.color }}>
            <FontAwesomeIcon icon={cfg.icon} style={{ color: cfg.color }} />
            <span>{cfg.label}</span>
            <span className="jas-exec-board-count">{tasksByStatus[status].length}</span>
          </div>
          <div className="jas-exec-board-cards">
            {tasksByStatus[status].map((task) => (
              <div key={task.id} className="jas-exec-board-card">
                <div className="jas-exec-card-title">{task.title}</div>
                <div className="jas-exec-card-meta">
                  {task.phase && <span className="jas-exec-card-phase">{task.phase}</span>}
                  <span
                    className="jas-exec-card-priority"
                    style={{ color: (PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.medium).color }}
                  >
                    {(PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.medium).label}
                  </span>
                </div>
                {task.owner && <div className="jas-exec-card-owner">{task.owner}</div>}
                {task.due_date && <div className="jas-exec-card-due">{task.due_date}</div>}

                {/* Status move buttons */}
                {canWrite && (
                  <div className="jas-exec-card-actions">
                    {status !== 'done' && (
                      <button
                        onClick={() => {
                          const next = status === 'todo' ? 'in_progress' : 'done';
                          onUpdateTask(task.id, { status: next });
                        }}
                        title={status === 'todo' ? 'Start' : 'Complete'}
                      >
                        {status === 'todo' ? '▶ Start' : '✓ Done'}
                      </button>
                    )}
                    {status === 'in_progress' && (
                      <button onClick={() => onUpdateTask(task.id, { status: 'blocked' })} title="Mark blocked">
                        ⊘ Block
                      </button>
                    )}
                    {status === 'blocked' && (
                      <button onClick={() => onUpdateTask(task.id, { status: 'in_progress' })} title="Unblock">
                        ▶ Unblock
                      </button>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
};
```

---

## Step 6: Timeline View (Gantt-style — like Smartsheet)

The Timeline view renders a horizontal bar chart. Each task is a row with a bar representing its `estimated_days` (or `timeline_days`) and `due_date`. Dependencies are shown as connecting lines.

For Phase 1, keep this simple — no drag-to-resize. Just visual representation.

```jsx
const TimelineView = () => {
  // Compute date range
  const { minDate, maxDate, totalDays } = useMemo(() => {
    const now = new Date();
    let earliest = now;
    let latest = new Date(now.getTime() + 90 * 24 * 60 * 60 * 1000); // default 90 days

    tasks.forEach((t) => {
      if (t.due_date) {
        const d = new Date(t.due_date);
        if (d < earliest) earliest = d;
        if (d > latest) latest = d;
      }
    });

    const total = Math.max(1, Math.ceil((latest - earliest) / (24 * 60 * 60 * 1000)));
    return { minDate: earliest, maxDate: latest, totalDays: total };
  }, [tasks]);

  const dayToPercent = (date) => {
    const d = new Date(date);
    const diff = Math.ceil((d - minDate) / (24 * 60 * 60 * 1000));
    return Math.max(0, Math.min(100, (diff / totalDays) * 100));
  };

  return (
    <div className="jas-exec-timeline">
      {/* Header with date markers */}
      <div className="jas-exec-timeline-header">
        {/* Generate monthly markers */}
      </div>

      {/* Task rows */}
      {tasks.map((task) => {
        const est = task.estimated_days || task.timeline_days || 7;
        const endDate = task.due_date || null;
        const startDate = endDate
          ? new Date(new Date(endDate).getTime() - est * 24 * 60 * 60 * 1000)
          : new Date();

        const left = dayToPercent(startDate);
        const width = Math.max(2, (est / totalDays) * 100);
        const statusColor = (STATUS_CONFIG[task.status] || STATUS_CONFIG.todo).color;

        return (
          <div key={task.id} className="jas-exec-timeline-row">
            <div className="jas-exec-timeline-label">
              <span className="jas-exec-timeline-title">{task.title}</span>
              <span className="jas-exec-timeline-owner">{task.owner || ''}</span>
            </div>
            <div className="jas-exec-timeline-track">
              <div
                className="jas-exec-timeline-bar"
                style={{
                  left: `${left}%`,
                  width: `${width}%`,
                  backgroundColor: statusColor,
                }}
                title={`${task.title}: ${est} days, ${task.status}`}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
};
```

---

## Step 7: Wire WBS refresh to tab reactivity

### File: `/frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`

The existing `wbsMutationVersion` effect (line 754-759) already calls `refreshThreadWbs`. But the Execution tab needs to react when:

1. **The chat agent mutates WBS** — already handled via `applyMutationRefreshes` → `wbsMutationVersion` bump → `refreshThreadWbs`
2. **The user opens the Execution tab** — add refresh in tab click handler (Step 2c above)
3. **The user makes an inline edit** — the `onUpdateTask`/`onAddTask`/`onRemoveTask` callbacks call chat command handlers which upsert then show toast, but they don't refresh `threadWbs` state. Fix:

After each WBS mutation handler (`WBS_ADD_TASK`, `WBS_UPDATE_TASK`, `WBS_REMOVE_TASK`, `WBS_ADD_DEPENDENCY`), add at the end of the try block (after the upsert succeeds):

```javascript
setWbsMutationVersion((prev) => prev + 1);
```

This triggers the existing effect that calls `refreshThreadWbs`, which updates `threadWbs` state, which rerenders the ExecutionPanel.

---

## Step 8: AI agent conversation awareness

### File: `/backend/app/routes/ai_agent.py`

The AI system prompt (the large string starting around line ~806) should include awareness of the Execution tab. Find the section where tools are described and add context:

In the system prompt section that describes WBS tools, add:

```
The user can see the Execution tab which shows a visual representation of the WBS — a list view with phases and tasks, a Kanban board grouped by status, and a timeline view. When you add, update, or remove tasks, the UI updates in real-time. The user can also make direct inline edits (changing status, title, owner, due_date) from the UI, which call the same mutation endpoints.

When the user asks to "build an execution plan" or "create a project plan" or "generate tasks", use the ai-wbs generation to create a comprehensive WBS from the scorecard analysis. After generating, summarize what was created so the user knows to check the Execution tab.

When the user references tasks by name or asks to change statuses, priorities, owners, or dates, use the appropriate WBS tools. Always confirm what you changed.
```

### Existing tool gaps

The backend `update_wbs_task` tool only allows updating these fields: `title`, `description`, `priority`, `estimated_days`, `suggested_role`. It does **not** allow updating `status`, `owner`, `due_date`, or `phase` via the agent tool.

**This is a critical gap.** The user will ask the chat agent "mark task X as done" or "assign task X to Sarah" and the agent will fail.

#### Fix in: `/backend/app/routes/ai_agent.py`

Find the `update_wbs_task` tool definition (line ~882) and expand the allowed fields:

Current:
```python
"field": {
    "type": "string",
    "description": "The field to update.",
    "enum": ["title", "description", "priority", "estimated_days", "suggested_role"],
},
```

Change to:
```python
"field": {
    "type": "string",
    "description": "The field to update.",
    "enum": [
        "title", "description", "priority", "estimated_days",
        "suggested_role", "status", "owner", "due_date", "phase",
    ],
},
```

Then in the `_execute_mutation_tool` function for `update_wbs_task` (line ~1051), the field assignment logic already uses:
```python
task[field] = new_value
```

But add validation for the new fields:

```python
if field == "status" and new_value not in {"todo", "in_progress", "blocked", "done"}:
    return _tool_error(f"Invalid status: {new_value}. Must be one of: todo, in_progress, blocked, done.")
if field == "priority" and new_value not in {"high", "medium", "low"}:
    return _tool_error(f"Invalid priority: {new_value}. Must be one of: high, medium, low.")
if field == "due_date" and new_value is not None:
    # Basic date validation
    try:
        datetime.strptime(str(new_value), "%Y-%m-%d")
    except (ValueError, TypeError):
        return _tool_error(f"Invalid date format: {new_value}. Use YYYY-MM-DD.")
```

---

## Step 9: Role gating on the Execution tab

Use the same org role system from the sidebar spec:

| Role | Can see Execution tab | Can edit tasks | Can add/remove tasks | Can ask AI to modify |
|---|---|---|---|---|
| Owner/Admin | Yes | Yes | Yes | Yes |
| Creator | Yes | Yes (own projects) | Yes | Yes |
| Collaborator | Yes (shared projects) | Yes (shared projects) | No | Yes (within shared) |
| Viewer | Yes (shared projects) | No | No | No |
| Individual (Free) | No (plan-gated) | N/A | N/A | N/A |
| Individual (Essential+) | Yes | Yes | Yes | Yes |

The `canWrite` prop passed to `ExecutionPanel` handles this:

```javascript
const canWriteWbs = canUseWbsWrite && !effectiveIsViewer;
```

For collaborators on shared projects, `canUseWbsWrite` is already plan-gated (Essential+), and they have `canEditProjects === true`, so they can edit but not add/remove. To enforce this granularity, split the prop:

```javascript
const canEditWbsTasks = canUseWbsWrite && !effectiveIsViewer;
const canAddRemoveWbsTasks = canEditWbsTasks && !effectiveIsCollaborator;
```

Pass both to ExecutionPanel:
```jsx
<ExecutionPanel
  canEdit={canEditWbsTasks}
  canAddRemove={canAddRemoveWbsTasks}
  isViewer={effectiveIsViewer}
  ...
/>
```

---

## Step 10: Sync indicator and connector status

If the thread has an active sync profile (Jira/Workfront/Smartsheet), show a sync status bar at the top of the Execution tab.

### Data source

The connector state is already available through the existing connector APIs. Add a small fetch:

```javascript
const [syncStatus, setSyncStatus] = useState(null);

useEffect(() => {
  if (!sessionId || planCategory === 'individual') return;
  authFetch(`/api/v1/connectors/threads/${sessionId}/sync-profile`)
    .then(res => res.ok ? res.json() : null)
    .then(data => setSyncStatus(data))
    .catch(() => setSyncStatus(null));
}, [sessionId, planCategory, authFetch]);
```

### Render sync bar

```jsx
{syncStatus && syncStatus.connector_ids?.length > 0 && (
  <div className="jas-exec-sync-bar">
    <span>Synced with {syncStatus.connector_ids.join(', ')}</span>
    <span>Mode: {syncStatus.sync_mode}</span>
    {syncStatus.last_synced_at && (
      <span>Last sync: {new Date(syncStatus.last_synced_at).toLocaleString()}</span>
    )}
    <button onClick={() => {
      // Trigger manual sync for each connector
      syncStatus.connector_ids.forEach((connectorId) => {
        authFetch(`/api/v1/connectors/threads/${sessionId}/${connectorId}/sync`, { method: 'POST' });
      });
      showToast('Sync triggered', 'info');
    }}>
      Sync now
    </button>
  </div>
)}
```

---

## Step 11: CSS for ExecutionPanel

### Create: `/frontend/src/jaspenInterface/Workspace/components/ExecutionPanel.css`

Key layout rules:

```css
/* Container */
.jas-exec-panel { padding: 24px; max-width: 1200px; margin: 0 auto; }

/* Progress bar */
.jas-exec-progress { margin-bottom: 20px; }
.jas-exec-progress-bar {
  height: 6px; background: rgba(0,0,0,0.08); border-radius: 3px; overflow: hidden;
}
.jas-exec-progress-fill {
  height: 100%; background: #22c55e; border-radius: 3px; transition: width 0.3s;
}
.jas-exec-progress-stats {
  display: flex; gap: 16px; margin-top: 6px; font-size: 12px; opacity: 0.7;
}
.jas-exec-stat-blocked { color: #ef4444; }

/* View toggle */
.jas-exec-view-toggle {
  display: flex; gap: 4px; margin-bottom: 16px;
  border: 1px solid rgba(0,0,0,0.1); border-radius: 6px; padding: 2px; width: fit-content;
}
.jas-exec-view-toggle button {
  padding: 6px 12px; border: none; background: transparent; border-radius: 4px;
  cursor: pointer; font-size: 12px; display: flex; align-items: center; gap: 6px;
}
.jas-exec-view-toggle button.active { background: rgba(0,0,0,0.08); font-weight: 600; }

/* List view */
.jas-exec-phase { margin-bottom: 8px; }
.jas-exec-phase-header {
  display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  background: rgba(0,0,0,0.03); border-radius: 6px; border: none; width: 100%;
  cursor: pointer; font-size: 13px; font-weight: 600;
}
.jas-exec-phase-count, .jas-exec-phase-done { font-weight: 400; opacity: 0.6; font-size: 12px; }
.jas-exec-task-row {
  display: grid;
  grid-template-columns: 120px 1fr 70px 120px 100px 40px 30px 30px;
  align-items: center; gap: 8px; padding: 8px 12px 8px 32px;
  border-bottom: 1px solid rgba(0,0,0,0.05); font-size: 13px;
}
.jas-exec-task-title { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jas-exec-task-title.editable { cursor: text; }
.jas-exec-task-title.editable:focus { outline: 1px solid #3b82f6; border-radius: 2px; padding: 0 4px; }
.jas-exec-status-select {
  border: 1px solid rgba(0,0,0,0.1); border-radius: 4px; padding: 2px 4px;
  font-size: 11px; background: transparent;
}
.jas-exec-priority { font-size: 11px; font-weight: 600; text-transform: uppercase; }
.jas-exec-owner-input {
  border: 1px solid transparent; border-radius: 4px; padding: 2px 6px;
  font-size: 12px; background: transparent; width: 100%;
}
.jas-exec-owner-input:focus { border-color: rgba(0,0,0,0.15); background: rgba(0,0,0,0.02); }
.jas-exec-date-input { border: 1px solid transparent; font-size: 12px; background: transparent; }
.jas-exec-deps { font-size: 11px; opacity: 0.5; }
.jas-exec-remove-btn {
  border: none; background: transparent; color: #ef4444; opacity: 0.3;
  cursor: pointer; padding: 4px;
}
.jas-exec-remove-btn:hover { opacity: 1; }
.jas-exec-add-task-btn {
  border: none; background: transparent; padding: 6px 12px 6px 32px;
  font-size: 12px; opacity: 0.5; cursor: pointer; display: flex; align-items: center; gap: 6px;
}
.jas-exec-add-task-btn:hover { opacity: 1; }
.jas-exec-add-row { padding: 4px 12px 4px 32px; }
.jas-exec-add-row input {
  width: 100%; padding: 6px 8px; border: 1px solid #3b82f6; border-radius: 4px; font-size: 13px;
}

/* Board view */
.jas-exec-board { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; }
.jas-exec-board-column {
  border: 1px solid rgba(0,0,0,0.08); border-radius: 8px; min-height: 200px;
  display: flex; flex-direction: column;
}
.jas-exec-board-column-header {
  padding: 12px; border-top: 3px solid; font-weight: 600; font-size: 13px;
  display: flex; align-items: center; gap: 8px; border-radius: 8px 8px 0 0;
}
.jas-exec-board-count {
  margin-left: auto; font-weight: 400; opacity: 0.5; font-size: 12px;
}
.jas-exec-board-cards { padding: 8px; display: flex; flex-direction: column; gap: 8px; flex: 1; }
.jas-exec-board-card {
  padding: 12px; border: 1px solid rgba(0,0,0,0.08); border-radius: 6px;
  background: var(--card-bg, #fff); font-size: 13px;
}
.jas-exec-card-title { font-weight: 600; margin-bottom: 6px; }
.jas-exec-card-meta { display: flex; gap: 8px; font-size: 11px; margin-bottom: 4px; }
.jas-exec-card-phase {
  background: rgba(0,0,0,0.05); padding: 1px 6px; border-radius: 3px;
}
.jas-exec-card-owner { font-size: 11px; opacity: 0.7; }
.jas-exec-card-due { font-size: 11px; opacity: 0.5; }
.jas-exec-card-actions {
  display: flex; gap: 4px; margin-top: 8px;
}
.jas-exec-card-actions button {
  padding: 3px 8px; font-size: 10px; border: 1px solid rgba(0,0,0,0.15);
  border-radius: 4px; background: transparent; cursor: pointer;
}
.jas-exec-card-actions button:hover { background: rgba(0,0,0,0.05); }

/* Timeline view */
.jas-exec-timeline { overflow-x: auto; }
.jas-exec-timeline-row {
  display: grid; grid-template-columns: 200px 1fr; align-items: center;
  border-bottom: 1px solid rgba(0,0,0,0.05); height: 36px;
}
.jas-exec-timeline-label { padding: 0 12px; display: flex; flex-direction: column; }
.jas-exec-timeline-title { font-size: 12px; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.jas-exec-timeline-owner { font-size: 10px; opacity: 0.5; }
.jas-exec-timeline-track { position: relative; height: 100%; }
.jas-exec-timeline-bar {
  position: absolute; top: 8px; height: 20px; border-radius: 4px; min-width: 8px;
  opacity: 0.8; transition: all 0.2s;
}
.jas-exec-timeline-bar:hover { opacity: 1; }

/* Sync bar */
.jas-exec-sync-bar {
  display: flex; align-items: center; gap: 16px; padding: 8px 16px;
  background: rgba(59,130,246,0.05); border: 1px solid rgba(59,130,246,0.15);
  border-radius: 6px; font-size: 12px; margin-bottom: 16px;
}
.jas-exec-sync-bar button {
  margin-left: auto; padding: 4px 12px; border: 1px solid rgba(59,130,246,0.3);
  border-radius: 4px; background: transparent; cursor: pointer; font-size: 11px;
}

/* Empty state */
.jas-exec-empty { text-align: center; padding: 64px 24px; }
.jas-exec-empty h3 { margin: 0 0 8px; }
.jas-exec-empty p { opacity: 0.6; margin: 0 0 24px; }
.jas-exec-empty-actions { display: flex; gap: 12px; justify-content: center; }
.jas-exec-btn-primary {
  padding: 10px 20px; background: #3b82f6; color: #fff; border: none;
  border-radius: 6px; cursor: pointer; font-weight: 600;
}
.jas-exec-btn-secondary {
  padding: 10px 20px; background: transparent; border: 1px solid rgba(0,0,0,0.15);
  border-radius: 6px; cursor: pointer; display: flex; align-items: center; gap: 6px;
}

/* Viewer lock overlay */
.jas-exec-viewer-notice {
  padding: 8px 16px; background: rgba(0,0,0,0.03); border-radius: 6px;
  font-size: 12px; display: flex; align-items: center; gap: 8px; margin-bottom: 16px;
}
```

---

## Build Sequence

1. Add `WBS_REMOVE_TASK` to ChatActionTypes and handler in JaspenWorkspace.jsx
2. Fix `threadWbs` state to be readable (remove the unused-variable destructure)
3. Expand backend `update_wbs_task` tool to allow `status`, `owner`, `due_date`, `phase` fields
4. Add field validation for the new fields in `_execute_mutation_tool`
5. Create `ExecutionPanel.jsx` with List view, Board view, Timeline view
6. Create `ExecutionPanel.css`
7. Add the "Execution" tab to the workspace tab bar
8. Wire tab click to refresh WBS
9. Wire `ExecutionPanel` callbacks to existing chat command handlers
10. Add `setWbsMutationVersion` bump to each WBS mutation handler
11. Add sync status fetch and display
12. Update AI agent system prompt to reference the Execution tab
13. Add role gating (`canEdit` / `canAddRemove` / `isViewer` props)
14. Test: generate WBS from chat → verify it appears in Execution tab
15. Test: inline edit task status/title → verify backend persistence
16. Test: ask agent "mark task X as done" → verify Execution tab updates
17. Test: viewer sees read-only Execution tab
18. Test: collaborator can edit but not add/remove tasks

---

## What this achieves vs PM competitors

| Capability | Jira | Smartsheet | Workfront | Jaspen (after this) |
|---|---|---|---|---|
| Task list with phases | ✓ | ✓ | ✓ | ✓ |
| Kanban board | ✓ | ✗ | ✓ | ✓ |
| Timeline/Gantt | ✗ (plugin) | ✓ | ✓ | ✓ (basic) |
| AI-generated plan | ✗ | ✗ | ✗ | ✓ |
| Chat-driven task edits | ✗ | ✗ | ✗ | ✓ |
| Strategic → Execution link | ✗ | ✗ | ✗ | ✓ (scorecard → WBS) |
| External PM sync | N/A | N/A | N/A | ✓ (Jira, Workfront, Smartsheet) |
| Inline editable | ✓ | ✓ | ✓ | ✓ |
| Dependency tracking | ✓ | ✓ | ✓ | ✓ |
| Role-based access | ✓ | ✓ | ✓ | ✓ |

---

## Out of scope for this pass

- Drag-and-drop reordering (list view) and drag between columns (board view)
- Critical path analysis / auto-scheduling
- Resource allocation / capacity planning view
- Budget / cost tracking per task
- Burndown chart
- Sprint planning
- Task comments / activity log
- File attachments on tasks
- Subtask hierarchy (WBS currently flat within phases)
- Email notifications for task assignments
- Mobile-responsive Kanban
