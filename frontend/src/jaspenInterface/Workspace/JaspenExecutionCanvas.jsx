// ============================================================================
// File: frontend/src/jaspenInterface/Workspace/JaspenExecutionCanvas.jsx
// Purpose: The Execution Plan canvas inside the standalone Workspace editor.
//          Renders phases → tasks with inline editing. Direct user edits are
//          free; the scoped chat sidebar can also drive AI-assisted changes
//          (those cost credits). Saves go through PUT /threads/:tid/wbs.
//
// Design reference: Claude Design mockup "02 · Workspace editor"
// — Inter Tight UI, JetBrains Mono numerics, navy/rose/orange palette,
//   phase cards on a soft #f7f8fa background, generous whitespace.
//
// Status pills:
//   to do      → muted gray
//   in_progress → blue
//   blocked     → orange
//   done        → green
//
// Priority dots: critical=red, high=orange, medium=gray, low=light gray
//
// Editing model:
//   - Click title / description → contenteditable (commit on blur or Enter)
//   - Click owner avatar → free-text input (lightweight picker, v1)
//   - Click status pill → cycles through next status (v1)
//   - Drag handle visible on hover (drag-drop is v1.1)
//   - "+ Add task" link at the bottom of each phase
// ============================================================================

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faGripVertical, faPlus, faEllipsis, faCheck,
  faArrowRotateRight,
} from '@fortawesome/free-solid-svg-icons';

import { Jaspen } from './JaspenClient';

// ── Palette (matches Claude Design + existing Jaspen chrome) ───────────────
export const COLOR = {
  navy: '#161f3b',
  navy2: '#2c3656',
  ink: '#5a6585',
  mute: '#8a93ad',
  line: '#e4e8f0',
  line2: '#f1f3f8',
  bg: '#f7f8fa',
  cardBg: '#ffffff',
  rose: '#a0036c',
  roseTint: '#fbeaf3',
  roseLine: '#f1cfe1',
  green: '#10b981',
  greenTint: '#dff4e8',
  greenInk: '#0e6b3f',
  orange: '#f59e0b',
  orangeTint: '#fdf1d8',
  orangeInk: '#92590b',
  blue: '#3b82f6',
  blueTint: '#e9f0fe',
  blueInk: '#1e40af',
};

const STATUS_LABEL = {
  todo: 'To Do',
  in_progress: 'In Progress',
  blocked: 'Blocked',
  done: 'Done',
};
const STATUS_ORDER = ['todo', 'in_progress', 'blocked', 'done'];
const STATUS_STYLE = {
  todo:        { bg: COLOR.line2, ink: COLOR.ink,       dot: COLOR.mute   },
  in_progress: { bg: COLOR.blueTint,   ink: COLOR.blueInk,   dot: COLOR.blue   },
  blocked:     { bg: COLOR.orangeTint, ink: COLOR.orangeInk, dot: COLOR.orange },
  done:        { bg: COLOR.greenTint,  ink: COLOR.greenInk,  dot: COLOR.green  },
};

const PRIORITY_STYLE = {
  critical: { dot: '#dc2626', label: 'Critical' },
  high:     { dot: COLOR.orange, label: 'High'  },
  medium:   { dot: COLOR.mute, label: 'Medium'  },
  low:      { dot: '#cbd5e1', label: 'Low'      },
};

const normalizeStatus = (s) => {
  const v = String(s || '').toLowerCase().replace(/[\s-]/g, '_');
  if (STATUS_LABEL[v]) return v;
  if (v === 'inprogress' || v === 'in_progress') return 'in_progress';
  if (v === 'pending') return 'todo';
  return 'todo';
};
const normalizePriority = (p) => {
  const v = String(p || '').toLowerCase();
  if (PRIORITY_STYLE[v]) return v;
  return 'medium';
};

// Pull the initials for an owner string (e.g. "Alex Chen" → "AC")
const initialsOf = (name) => {
  const s = String(name || '').trim();
  if (!s) return '?';
  const parts = s.split(/\s+/).filter(Boolean);
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
};

// Deterministic avatar tint per owner so the same person always reads the same
const tintForOwner = (name) => {
  const palette = ['#a0036c', '#3b82f6', '#10b981', '#f59e0b', '#7c3aed', '#0891b2', '#db2777'];
  const s = String(name || '');
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (h * 31 + s.charCodeAt(i)) >>> 0;
  return palette[h % palette.length];
};

// ── Small UI atoms ─────────────────────────────────────────────────────────

export const Eyebrow = ({ children, color = COLOR.mute, style }) => (
  <span style={{
    fontFamily: 'JetBrains Mono, monospace',
    fontSize: 10.5, fontWeight: 600, color,
    letterSpacing: '0.08em', textTransform: 'uppercase',
    display: 'inline-flex', alignItems: 'center', gap: 6,
    ...style,
  }}>{children}</span>
);

export const Pill = ({ children, tone = 'default', style, ...rest }) => {
  const tones = {
    default: { bg: COLOR.line2,  ink: COLOR.navy,    border: COLOR.line },
    ghost:   { bg: 'transparent', ink: COLOR.ink,     border: COLOR.line },
    magenta: { bg: COLOR.roseTint, ink: COLOR.rose,  border: COLOR.roseLine },
    navy:    { bg: COLOR.navy,    ink: '#fff',        border: COLOR.navy },
  };
  const t = tones[tone] || tones.default;
  return (
    <span
      {...rest}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '4px 10px', borderRadius: 999,
        background: t.bg, color: t.ink,
        border: `1px solid ${t.border}`,
        fontSize: 12, lineHeight: 1.25, whiteSpace: 'nowrap',
        ...style,
      }}
    >{children}</span>
  );
};

export const Avatar = ({ name, size = 22 }) => {
  const bg = tintForOwner(name);
  return (
    <span style={{
      width: size, height: size, borderRadius: size / 2,
      background: bg, color: '#fff',
      display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
      fontSize: Math.max(9, Math.round(size * 0.42)), fontWeight: 600, letterSpacing: 0,
      flexShrink: 0,
    }}>{initialsOf(name)}</span>
  );
};

export const StatusPill = ({ status, onClick, interactive = true }) => {
  const s = normalizeStatus(status);
  const sty = STATUS_STYLE[s];
  return (
    <span
      onClick={interactive ? onClick : undefined}
      style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '3px 9px', borderRadius: 999,
        background: sty.bg, color: sty.ink,
        fontSize: 11.5, fontWeight: 500,
        cursor: interactive ? 'pointer' : 'default',
        userSelect: 'none', whiteSpace: 'nowrap',
      }}
      title={interactive ? 'Click to cycle status' : undefined}
    >
      <span style={{ width: 6, height: 6, borderRadius: 3, background: sty.dot }} />
      {STATUS_LABEL[s]}
    </span>
  );
};

export const PriorityDot = ({ priority }) => {
  const p = normalizePriority(priority);
  const sty = PRIORITY_STYLE[p];
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: COLOR.navy2 }}>
      <span style={{ width: 7, height: 7, borderRadius: 4, background: sty.dot }} />
      {sty.label}
    </span>
  );
};

// ── Editable text (contenteditable + commit on blur) ───────────────────────

export function EditableText({ value, onCommit, multiline = false, style, placeholder = '—' }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');
  useEffect(() => { setDraft(value || ''); }, [value]);

  const commit = () => {
    setEditing(false);
    const next = String(draft || '').trim();
    if (next !== String(value || '').trim()) onCommit?.(next);
  };

  if (!editing) {
    return (
      <span
        onClick={(e) => { e.stopPropagation(); setEditing(true); }}
        title="Click to edit"
        style={{
          ...style,
          cursor: 'text', borderRadius: 4, padding: '1px 4px', margin: '-1px -4px',
          display: 'inline-block', minHeight: 18, transition: 'background 120ms',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = COLOR.line2; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
      >
        {value || <span style={{ color: COLOR.mute }}>{placeholder}</span>}
      </span>
    );
  }

  if (multiline) {
    return (
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (e.key === 'Escape') { setDraft(value || ''); setEditing(false); }
        }}
        onClick={(e) => e.stopPropagation()}
        style={{
          ...style,
          width: '100%', minHeight: 56,
          border: `1px solid ${COLOR.line}`, borderRadius: 6,
          padding: '6px 8px', resize: 'vertical', fontFamily: 'inherit',
        }}
      />
    );
  }

  return (
    <input
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => {
        if (e.key === 'Enter') { e.preventDefault(); commit(); }
        if (e.key === 'Escape') { setDraft(value || ''); setEditing(false); }
      }}
      onClick={(e) => e.stopPropagation()}
      style={{
        ...style,
        width: '100%', border: `1px solid ${COLOR.line}`, borderRadius: 6,
        padding: '3px 6px', fontFamily: 'inherit',
      }}
    />
  );
}

// ── View switcher (List / Board / Timeline) ────────────────────────────────

export function ViewSwitcher({ value, onChange }) {
  const opts = [
    { key: 'list', label: 'List' },
    { key: 'board', label: 'Board' },
    { key: 'timeline', label: 'Timeline' },
  ];
  return (
    <div style={{
      display: 'inline-flex', padding: 3, borderRadius: 8,
      background: COLOR.line2, border: `1px solid ${COLOR.line}`,
    }}>
      {opts.map((o) => {
        const active = value === o.key;
        return (
          <button
            key={o.key}
            type="button"
            onClick={() => onChange?.(o.key)}
            style={{
              padding: '5px 12px', borderRadius: 6, border: 'none',
              background: active ? '#fff' : 'transparent',
              color: active ? COLOR.navy : COLOR.ink,
              fontSize: 12.5, fontWeight: active ? 600 : 500,
              cursor: 'pointer',
              boxShadow: active ? '0 1px 3px rgba(15,23,42,0.08)' : 'none',
            }}
          >
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

// ── Owner summary chip (header strip) ──────────────────────────────────────
export const OwnerChip = ({ name, count }) => (
  <div style={{
    display: 'inline-flex', alignItems: 'center', gap: 6,
    padding: '3px 10px 3px 4px', borderRadius: 999,
    background: COLOR.line2, border: `1px solid ${COLOR.line}`,
    whiteSpace: 'nowrap',
  }}>
    <Avatar name={name} size={20} />
    <span style={{ fontSize: 11.5, color: COLOR.navy2, fontWeight: 500 }}>
      {String(name).split(/\s+/)[0]}
    </span>
    <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: COLOR.mute }}>· {count}</span>
  </div>
);

// ── Task row (the unit of editing) ─────────────────────────────────────────

export function TaskRow({ task, onUpdate, onReorder, isFirst, isLast, phaseName }) {
  const [showActions, setShowActions] = useState(false);
  const [dragOverEdge, setDragOverEdge] = useState(null); // 'top' | 'bottom' | null
  const status = normalizeStatus(task.status);
  const priority = normalizePriority(task.priority);
  const dueOrWeek = task.due_date || (task.timeline_days
    ? `${task.timeline_days} day${task.timeline_days === 1 ? '' : 's'}`
    : null);

  const cycleStatus = () => {
    const i = STATUS_ORDER.indexOf(status);
    const next = STATUS_ORDER[(i + 1) % STATUS_ORDER.length];
    onUpdate?.({ status: next });
  };

  // HTML5 drag-drop handlers — write the task id to dataTransfer so the
  // drop target can locate the source. Same logic works across phases.
  const onDragStart = (e) => {
    if (!task?.id) return;
    e.dataTransfer.setData('text/plain', String(task.id));
    e.dataTransfer.effectAllowed = 'move';
    // Make the cursor read as 'grabbing' during drag
    e.currentTarget.style.opacity = '0.55';
  };
  const onDragEnd = (e) => {
    e.currentTarget.style.opacity = '1';
    setDragOverEdge(null);
  };
  const onDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const rect = e.currentTarget.getBoundingClientRect();
    const halfway = rect.top + rect.height / 2;
    setDragOverEdge(e.clientY < halfway ? 'top' : 'bottom');
  };
  const onDragLeave = () => setDragOverEdge(null);
  const onDrop = (e) => {
    e.preventDefault();
    const sourceId = e.dataTransfer.getData('text/plain');
    setDragOverEdge(null);
    if (!sourceId || sourceId === String(task.id)) return;
    onReorder?.({
      sourceId,
      targetId: task.id,
      position: dragOverEdge === 'top' ? 'before' : 'after',
      targetPhase: phaseName,
    });
  };

  return (
    <div
      draggable={!!task?.id}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onMouseEnter={() => setShowActions(true)}
      onMouseLeave={() => setShowActions(false)}
      style={{
        display: 'grid',
        gridTemplateColumns: '20px minmax(0, 1fr) 110px 150px 100px 130px 28px',
        alignItems: 'center', gap: 14,
        padding: '12px 4px',
        borderTop: isFirst
          ? (dragOverEdge === 'top' ? `2px solid ${COLOR.rose}` : 'none')
          : (dragOverEdge === 'top' ? `2px solid ${COLOR.rose}` : `1px solid ${COLOR.line2}`),
        borderBottom: dragOverEdge === 'bottom' ? `2px solid ${COLOR.rose}` : 'none',
        position: 'relative',
      }}
    >
      {/* Drag handle */}
      <span style={{
        opacity: showActions ? 1 : 0,
        color: COLOR.mute, cursor: 'grab', textAlign: 'center',
        transition: 'opacity 120ms',
      }}>
        <FontAwesomeIcon icon={faGripVertical} style={{ fontSize: 12 }} />
      </span>

      {/* Title + description (acceptance criteria live inline in description) */}
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 13.5, color: COLOR.navy, fontWeight: 500, lineHeight: 1.35 }}>
          <EditableText
            value={task.title || ''}
            onCommit={(v) => onUpdate?.({ title: v })}
            placeholder="Untitled task"
          />
        </div>
        {(task.description || task.acceptance) && (
          <div style={{
            fontSize: 11.5, color: COLOR.ink, lineHeight: 1.5, marginTop: 4,
            paddingLeft: 0,
          }}>
            <EditableText
              multiline
              value={task.description || task.acceptance || ''}
              onCommit={(v) => onUpdate?.({ description: v })}
              placeholder="Add description / acceptance criteria…"
              style={{ fontSize: 11.5, color: COLOR.ink, lineHeight: 1.5 }}
            />
          </div>
        )}
        {!task.description && !task.acceptance && (
          <div style={{ fontSize: 11.5, color: COLOR.mute, lineHeight: 1.5, marginTop: 4 }}>
            <EditableText
              multiline
              value=""
              onCommit={(v) => onUpdate?.({ description: v })}
              placeholder="Add description / acceptance criteria…"
              style={{ fontSize: 11.5, color: COLOR.mute, lineHeight: 1.5 }}
            />
          </div>
        )}
      </div>

      {/* Priority */}
      <PriorityDot priority={priority} />

      {/* Owner */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 0 }}>
        <Avatar name={task.owner || task.suggested_role || ''} size={22} />
        <span style={{ fontSize: 12.5, color: COLOR.navy2, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          <EditableText
            value={task.owner || task.suggested_role || ''}
            onCommit={(v) => onUpdate?.({ owner: v })}
            placeholder="Unassigned"
          />
        </span>
      </div>

      {/* Due / week */}
      <div style={{ fontSize: 12, color: COLOR.ink, fontFamily: 'JetBrains Mono, monospace', whiteSpace: 'nowrap' }}>
        <EditableText
          value={dueOrWeek || ''}
          onCommit={(v) => onUpdate?.({ due_date: v })}
          placeholder="—"
          style={{ fontSize: 12, color: COLOR.ink, fontFamily: 'JetBrains Mono, monospace' }}
        />
      </div>

      {/* Status */}
      <StatusPill status={status} onClick={cycleStatus} />

      {/* Kebab menu (no-op for v1) */}
      <span style={{
        opacity: showActions ? 1 : 0,
        color: COLOR.mute, textAlign: 'center', cursor: 'pointer',
        transition: 'opacity 120ms',
      }}>
        <FontAwesomeIcon icon={faEllipsis} style={{ fontSize: 13 }} />
      </span>
    </div>
  );
}

// ── Phase card (header + task rows + add row) ──────────────────────────────

export function PhaseCard({ phase, tasks, onUpdateTask, onAddTask, onReorder }) {
  const [emptyDragOver, setEmptyDragOver] = useState(false);
  const doneCount = tasks.filter((t) => normalizeStatus(t.status) === 'done').length;

  // Drop handlers for the empty zone at the END of the phase: lets the user
  // drop a task from another phase into this one (becomes the last task).
  const onEmptyDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setEmptyDragOver(true);
  };
  const onEmptyDragLeave = () => setEmptyDragOver(false);
  const onEmptyDrop = (e) => {
    e.preventDefault();
    setEmptyDragOver(false);
    const sourceId = e.dataTransfer.getData('text/plain');
    if (!sourceId) return;
    onReorder?.({
      sourceId,
      targetId: null,
      position: 'end-of-phase',
      targetPhase: phase.title,
    });
  };

  return (
    <div style={{
      background: COLOR.cardBg,
      border: `1px solid ${COLOR.line}`,
      borderRadius: 16,
      boxShadow: '0 1px 2px rgba(22,31,59,0.03)',
      padding: '4px 22px 8px',
    }}>
      {/* Header */}
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 14,
        padding: '16px 0 14px', borderBottom: `1px solid ${COLOR.line2}`,
      }}>
        <Eyebrow color={COLOR.mute}>{`Phase ${phase.num}`}</Eyebrow>
        <span style={{ fontSize: 15, fontWeight: 600, color: COLOR.navy, letterSpacing: '-0.005em' }}>
          {phase.title}
        </span>
        {phase.weeks && (
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: COLOR.mute }}>
            {phase.weeks}
          </span>
        )}
        <div style={{ flex: 1 }} />
        <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11.5, color: COLOR.ink }}>
          {doneCount} / {tasks.length} complete
        </span>
      </div>

      {/* Tasks */}
      <div
        onDragOver={tasks.length === 0 ? onEmptyDragOver : undefined}
        onDragLeave={tasks.length === 0 ? onEmptyDragLeave : undefined}
        onDrop={tasks.length === 0 ? onEmptyDrop : undefined}
        style={tasks.length === 0 && emptyDragOver ? { background: COLOR.roseTint, borderRadius: 8 } : undefined}
      >
        {tasks.length === 0 && (
          <div style={{ padding: '14px 4px', fontSize: 12, color: COLOR.mute }}>
            {emptyDragOver ? 'Drop here to move into this phase' : 'No tasks in this phase yet.'}
          </div>
        )}
        {tasks.map((t, i) => (
          <TaskRow
            key={t.id || i}
            task={t}
            isFirst={i === 0}
            isLast={i === tasks.length - 1}
            phaseName={phase.title}
            onUpdate={(patch) => onUpdateTask(t.id, patch)}
            onReorder={onReorder}
          />
        ))}
      </div>

      {/* Add task / drop-to-end-of-phase zone */}
      <div
        onClick={() => onAddTask(phase.title)}
        onDragOver={onEmptyDragOver}
        onDragLeave={onEmptyDragLeave}
        onDrop={onEmptyDrop}
        style={{
          padding: '12px 4px', cursor: 'pointer',
          fontSize: 12.5, color: emptyDragOver ? COLOR.rose : COLOR.mute,
          display: 'flex', alignItems: 'center', gap: 8,
          borderTop: emptyDragOver ? `2px dashed ${COLOR.rose}` : `1px solid ${COLOR.line2}`,
          background: emptyDragOver && tasks.length > 0 ? COLOR.roseTint : 'transparent',
          borderRadius: emptyDragOver ? 6 : 0,
        }}
      >
        <FontAwesomeIcon icon={faPlus} style={{ fontSize: 10 }} />
        {emptyDragOver ? 'Drop to add to end of phase' : 'Add task'}
      </div>
    </div>
  );
}

// ── Board view (Kanban by status) ──────────────────────────────────────────

const BOARD_COLUMNS = [
  { id: 'todo',        label: 'To Do',       dot: COLOR.mute   },
  { id: 'in_progress', label: 'In Progress', dot: COLOR.blue   },
  { id: 'blocked',     label: 'Blocked',     dot: COLOR.orange },
  { id: 'done',        label: 'Done',        dot: COLOR.green  },
];

// Card rendered inside a Kanban column.
function BoardCard({ task, onUpdate, onColumnDrop }) {
  const [hover, setHover] = useState(false);
  const priority = normalizePriority(task?.priority);
  const dot = PRIORITY_STYLE[priority].dot;

  const onDragStart = (e) => {
    if (!task?.id) return;
    e.dataTransfer.setData('text/plain', String(task.id));
    e.dataTransfer.effectAllowed = 'move';
    e.currentTarget.style.opacity = '0.55';
  };
  const onDragEnd = (e) => { e.currentTarget.style.opacity = '1'; };

  return (
    <div
      draggable={!!task?.id}
      onDragStart={onDragStart}
      onDragEnd={onDragEnd}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        position: 'relative',
        background: '#fff',
        border: `1px solid ${COLOR.line}`,
        borderRadius: 10,
        padding: '11px 12px 10px',
        boxShadow: hover ? '0 6px 18px rgba(22,31,59,0.10), 0 0 0 1px rgba(22,31,59,0.04)' : '0 1px 2px rgba(22,31,59,0.04)',
        cursor: 'grab',
      }}
    >
      {/* priority dot + title */}
      <div style={{ display: 'flex', gap: 9, alignItems: 'flex-start', marginBottom: 9 }}>
        <span style={{ width: 7, height: 7, borderRadius: 4, background: dot, marginTop: 6, flex: '0 0 auto' }} />
        <div style={{
          fontSize: 13, fontWeight: 500, color: COLOR.navy, lineHeight: 1.35,
          display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
        }}>{task?.title || 'Untitled task'}</div>
      </div>

      {/* phase pill */}
      {task?.phase && (
        <div style={{ marginBottom: 10 }}>
          <span style={{
            display: 'inline-block', padding: '2px 7px', borderRadius: 4,
            background: COLOR.line2,
            fontFamily: 'JetBrains Mono, monospace',
            fontSize: 10, fontWeight: 600, color: COLOR.ink,
            letterSpacing: '0.06em', textTransform: 'uppercase',
          }}>{task.phase}</span>
        </div>
      )}

      {/* owner + due */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <Avatar name={task?.owner || task?.suggested_role || ''} size={20} />
        <span style={{ fontSize: 12, color: COLOR.navy2, fontWeight: 500 }}>
          {String(task?.owner || task?.suggested_role || 'Unassigned').split(/\s+/)[0]}
        </span>
        <span style={{ flex: 1 }} />
        {task?.due_date && (
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: COLOR.ink }}>
            {task.due_date}
          </span>
        )}
      </div>

      {/* hover ⋯ */}
      {hover && (
        <span style={{ position: 'absolute', top: 8, right: 8, color: COLOR.mute }}>
          <FontAwesomeIcon icon={faEllipsis} style={{ fontSize: 11 }} />
        </span>
      )}
    </div>
  );
}

function BoardColumn({ col, tasks, onColumnDrop }) {
  const [hover, setHover] = useState(false);
  const onDragOver = (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setHover(true);
  };
  const onDragLeave = () => setHover(false);
  const onDrop = (e) => {
    e.preventDefault();
    setHover(false);
    const sourceId = e.dataTransfer.getData('text/plain');
    if (!sourceId) return;
    onColumnDrop?.(sourceId, col.id);
  };

  return (
    <div
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      style={{
        flex: 1, minWidth: 0,
        display: 'flex', flexDirection: 'column',
        background: hover ? COLOR.roseTint : COLOR.line2,
        border: `1px solid ${hover ? COLOR.rose : COLOR.line}`,
        borderRadius: 14,
        padding: '14px 12px',
        minHeight: 0, transition: 'background 120ms, border-color 120ms',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, padding: '0 4px' }}>
        <span style={{ width: 8, height: 8, borderRadius: 4, background: col.dot }} />
        <span style={{ fontSize: 12.5, fontWeight: 600, color: COLOR.navy, letterSpacing: '-0.005em', textTransform: 'uppercase' }}>
          {col.label}
        </span>
        <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 11, color: COLOR.mute, fontWeight: 500 }}>
          {tasks.length}
        </span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, overflowY: 'auto', minHeight: 0 }}>
        {tasks.length === 0 && col.id === 'done' && (
          <div style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            padding: '40px 12px',
            border: `1.5px dashed ${COLOR.line}`, borderRadius: 10,
            fontSize: 12, color: COLOR.mute, textAlign: 'center',
          }}>Drop here when complete</div>
        )}
        {tasks.length === 0 && col.id !== 'done' && (
          <div style={{ padding: '14px 4px', fontSize: 11, color: COLOR.mute, fontStyle: 'italic' }}>
            No tasks
          </div>
        )}
        {tasks.map((t) => (
          <BoardCard key={t.id} task={t} />
        ))}
      </div>
    </div>
  );
}

export function BoardView({ wbs, onColumnDrop }) {
  const buckets = useMemo(() => {
    const b = { todo: [], in_progress: [], blocked: [], done: [] };
    (wbs?.tasks || []).forEach((t) => {
      const s = normalizeStatus(t?.status);
      if (b[s]) b[s].push(t);
    });
    return b;
  }, [wbs]);

  return (
    <div style={{
      flex: 1, minHeight: 0, overflow: 'hidden',
      padding: '4px 32px 32px',
      display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 14,
    }}>
      {BOARD_COLUMNS.map((col) => (
        <BoardColumn
          key={col.id}
          col={col}
          tasks={buckets[col.id]}
          onColumnDrop={onColumnDrop}
        />
      ))}
    </div>
  );
}

// ── Timeline view (Gantt-style, 12 weekly columns) ─────────────────────────

const TIMELINE_WEEKS = 12;
// Phase tints — rotate through 4 themes
const PHASE_TINTS = [
  { tint: '#fbeaf3', stripe: COLOR.rose },
  { tint: '#e9f0fe', stripe: COLOR.blue },
  { tint: '#fff5e6', stripe: COLOR.orange },
  { tint: '#dff4e8', stripe: COLOR.green },
];

// Format a date as "May 21" for week headers.
const _formatShortDate = (d) => {
  if (!d) return '';
  const m = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][d.getMonth()];
  return `${m} ${d.getDate()}`;
};

// Build the 12 weekly columns starting from the earliest task due_date,
// or today if none have due dates.
function buildTimelineGrid(wbs) {
  const tasks = Array.isArray(wbs?.tasks) ? wbs.tasks : [];
  // Anchor: first due_date in the plan, else today.
  let anchor = null;
  tasks.forEach((t) => {
    const d = Date.parse(String(t?.due_date || ''));
    if (Number.isFinite(d) && (!anchor || d < anchor)) anchor = d;
  });
  if (!anchor) anchor = Date.now();
  // Walk backward to the Monday of the anchor's week.
  const start = new Date(anchor);
  start.setHours(0, 0, 0, 0);
  const dayIdx = (start.getDay() + 6) % 7; // 0 = Mon
  start.setDate(start.getDate() - dayIdx);

  const weeks = [];
  for (let i = 0; i < TIMELINE_WEEKS; i++) {
    const d = new Date(start);
    d.setDate(start.getDate() + i * 7);
    weeks.push({ n: i + 1, date: d });
  }
  return { weeks, gridStart: weeks[0].date };
}

// Map a task to its (startWeek, endWeek) integer indices [1..12]. Uses
// estimated_days/timeline_days to length the bar; uses due_date as the
// END of the bar when available.
function taskToWeekRange(task, weeks, gridStart) {
  const dueTs = Date.parse(String(task?.due_date || ''));
  const days = Math.max(1, Number(task?.estimated_days || task?.timeline_days || 5));
  if (Number.isFinite(dueTs)) {
    const endIdx = Math.floor((dueTs - gridStart.getTime()) / (7 * 86400 * 1000));
    const endWeek = Math.max(1, Math.min(TIMELINE_WEEKS, endIdx + 1));
    const span = Math.max(1, Math.ceil(days / 7));
    const startWeek = Math.max(1, endWeek - span + 1);
    return { startWeek, endWeek };
  }
  // No due date — fall back to "1 week starting at week 1" (Phase 1, etc.)
  // Caller composes per-phase fallback below.
  return null;
}

function GanttBar({ task, startWeek, endWeek, onUpdate }) {
  const priority = normalizePriority(task?.priority);
  const muted = priority === 'low';
  const color = muted ? COLOR.line2 : PRIORITY_STYLE[priority].dot;
  const inkColor = muted ? COLOR.navy : '#fff';
  const span = endWeek - startWeek + 1;
  const leftPct = ((startWeek - 1) / TIMELINE_WEEKS) * 100;
  const widthPct = (span / TIMELINE_WEEKS) * 100;

  return (
    <div
      style={{
        position: 'absolute',
        left: `calc(${leftPct}% + 6px)`,
        width: `calc(${widthPct}% - 12px)`,
        top: 7, bottom: 7,
        borderRadius: 7,
        background: color,
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '0 9px',
        color: inkColor,
        boxShadow: muted ? 'none' : '0 1px 2px rgba(22,31,59,0.10)',
        cursor: 'grab', overflow: 'hidden',
      }}
      title={task?.title}
    >
      <Avatar name={task?.owner || task?.suggested_role || ''} size={18} />
      <span style={{
        fontSize: 11.5, fontWeight: 600, flex: 1,
        whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
        color: inkColor, letterSpacing: '-0.005em',
      }}>{task?.title || 'Untitled task'}</span>
      {span >= 2 && task?.due_date && (
        <span style={{
          fontFamily: 'JetBrains Mono, monospace', fontSize: 10, fontWeight: 600,
          color: muted ? COLOR.ink : 'rgba(255,255,255,0.85)', flex: '0 0 auto',
        }}>{task.due_date}</span>
      )}
    </div>
  );
}

export function TimelineView({ wbs, phases }) {
  const { weeks, gridStart } = useMemo(() => buildTimelineGrid(wbs), [wbs]);
  const LEFT_W = 308;
  const ROW_H = 46;
  const HEADER_H = 56;

  // Today line position (% across the 12-week range)
  const todayFrac = (() => {
    const t = (Date.now() - gridStart.getTime()) / (TIMELINE_WEEKS * 7 * 86400 * 1000);
    return Math.max(0, Math.min(1, t));
  })();

  return (
    <div style={{ padding: '4px 32px 22px', flex: 1, minHeight: 0, overflow: 'hidden', display: 'flex' }}>
      <div style={{
        flex: 1, minWidth: 0,
        background: '#fff', border: `1px solid ${COLOR.line}`, borderRadius: 14,
        display: 'flex', flexDirection: 'column', overflow: 'hidden',
        position: 'relative',
      }}>
        {/* Week header */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: `${LEFT_W}px 1fr`,
          height: HEADER_H, flex: '0 0 auto',
          borderBottom: `1px solid ${COLOR.line}`,
          background: '#fff', zIndex: 2,
        }}>
          <div style={{ padding: '0 22px', display: 'flex', alignItems: 'center' }}>
            <Eyebrow>Phase &nbsp;·&nbsp; Task</Eyebrow>
          </div>
          <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: `repeat(${TIMELINE_WEEKS}, 1fr)` }}>
            {weeks.map((w, i) => (
              <div key={w.n} style={{
                borderLeft: i === 0 ? 'none' : `1px solid ${COLOR.line2}`,
                padding: '8px 10px 0',
                display: 'flex', flexDirection: 'column', justifyContent: 'center', gap: 3,
              }}>
                <div style={{
                  fontFamily: 'JetBrains Mono, monospace',
                  fontSize: 10, color: COLOR.mute, letterSpacing: '0.06em', fontWeight: 600,
                }}>WK {w.n}</div>
                <div style={{
                  fontFamily: 'JetBrains Mono, monospace',
                  fontSize: 11, color: COLOR.navy, fontWeight: 600, letterSpacing: '0.02em',
                }}>{_formatShortDate(w.date)}</div>
              </div>
            ))}
          </div>
        </div>

        {/* Body */}
        <div style={{ flex: 1, overflow: 'auto', position: 'relative' }}>
          {phases.map((phase, pIdx) => {
            const tint = PHASE_TINTS[pIdx % PHASE_TINTS.length];
            const doneCount = phase.tasks.filter((t) => normalizeStatus(t.status) === 'done').length;
            return (
              <div key={phase.title} style={{
                position: 'relative',
                background: tint.tint,
                borderLeft: `3px solid ${tint.stripe}`,
              }}>
                {/* Phase header strip */}
                <div style={{
                  display: 'grid',
                  gridTemplateColumns: `${LEFT_W - 3}px 1fr`,
                  height: 38,
                  borderBottom: `1px solid ${COLOR.line}`,
                  alignItems: 'center',
                }}>
                  <div style={{ padding: '0 14px 0 19px', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{
                      fontFamily: 'JetBrains Mono, monospace',
                      fontSize: 10, fontWeight: 700,
                      color: tint.stripe, letterSpacing: '0.14em',
                    }}>PHASE {phase.num}</span>
                    <span style={{ fontSize: 12.5, fontWeight: 600, color: COLOR.navy }}>{phase.title}</span>
                  </div>
                  <div style={{ padding: '0 14px', display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 11, color: COLOR.ink }}>
                      <span style={{ fontFamily: 'JetBrains Mono, monospace', color: COLOR.navy, fontWeight: 600 }}>{doneCount}</span>
                      {' / '}{phase.tasks.length} complete
                    </span>
                  </div>
                </div>

                {/* Tasks */}
                {phase.tasks.map((t, tIdx) => {
                  // Try to derive week range from due_date; else fall back to a
                  // best-guess 2-week bar staggered by index inside the phase.
                  let range = taskToWeekRange(t, weeks, gridStart);
                  if (!range) {
                    const fallbackStart = Math.min(TIMELINE_WEEKS, 1 + tIdx);
                    const fallbackEnd = Math.min(TIMELINE_WEEKS, fallbackStart + 1);
                    range = { startWeek: fallbackStart, endWeek: fallbackEnd };
                  }
                  return (
                    <div key={t.id || tIdx} style={{
                      position: 'relative',
                      display: 'grid',
                      gridTemplateColumns: `${LEFT_W}px 1fr`,
                      height: ROW_H,
                      borderBottom: `1px solid ${COLOR.line2}`,
                    }}>
                      <div style={{
                        padding: '0 14px 0 22px',
                        display: 'flex', alignItems: 'center', gap: 10,
                        borderRight: `1px solid ${COLOR.line}`,
                        background: '#fff',
                      }}>
                        <span style={{
                          width: 6, height: 6, borderRadius: 4,
                          background: PRIORITY_STYLE[normalizePriority(t.priority)].dot,
                          opacity: normalizePriority(t.priority) === 'low' ? 0.6 : 1,
                          flex: '0 0 auto',
                        }} />
                        <span style={{
                          fontSize: 12.5, color: COLOR.navy, fontWeight: 500,
                          whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                          flex: 1, minWidth: 0,
                        }}>{t.title || 'Untitled task'}</span>
                        <Avatar name={t.owner || t.suggested_role || ''} size={20} />
                      </div>
                      <div style={{ position: 'relative' }}>
                        {/* Faint week gridlines */}
                        {weeks.map((w, i) => (
                          <div key={w.n} style={{
                            position: 'absolute',
                            left: `${(i / TIMELINE_WEEKS) * 100}%`,
                            top: 0, bottom: 0, width: 1,
                            background: i === 0 ? 'transparent' : COLOR.line2,
                          }} />
                        ))}
                        <GanttBar
                          task={t}
                          startWeek={range.startWeek}
                          endWeek={range.endWeek}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            );
          })}

          {/* Today vertical line */}
          {todayFrac > 0 && todayFrac < 1 && (
            <div style={{
              position: 'absolute',
              left: `calc(${LEFT_W}px + ${todayFrac} * (100% - ${LEFT_W}px))`,
              top: 0, bottom: 0,
              width: 0,
              borderLeft: `1.5px dashed ${COLOR.rose}`,
              pointerEvents: 'none', zIndex: 3,
            }}>
              <span style={{
                position: 'absolute', top: 6, left: -22,
                padding: '2px 7px', borderRadius: 4,
                background: COLOR.rose, color: '#fff',
                fontSize: 9.5, fontWeight: 700, letterSpacing: '0.12em',
                fontFamily: 'JetBrains Mono, monospace',
              }}>TODAY</span>
            </div>
          )}
        </div>

        {/* Legend */}
        <div style={{
          flex: '0 0 auto',
          padding: '10px 22px',
          borderTop: `1px solid ${COLOR.line}`,
          display: 'flex', alignItems: 'center', gap: 18,
          background: '#fff',
        }}>
          <Eyebrow>Priority</Eyebrow>
          {[
            { k: 'Critical', c: PRIORITY_STYLE.critical.dot },
            { k: 'High',     c: PRIORITY_STYLE.high.dot     },
            { k: 'Medium',   c: PRIORITY_STYLE.medium.dot   },
            { k: 'Low',      c: PRIORITY_STYLE.low.dot, muted: true },
          ].map((p) => (
            <span key={p.k} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 11.5, color: COLOR.ink }}>
              <span style={{ width: 14, height: 8, borderRadius: 3, background: p.c, opacity: p.muted ? 0.8 : 1 }} />
              {p.k}
            </span>
          ))}
          <div style={{ width: 1, height: 14, background: COLOR.line, margin: '0 4px' }} />
          <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7, fontSize: 11.5, color: COLOR.ink }}>
            <span style={{ display: 'inline-block', width: 18, height: 0, borderTop: `1.5px dashed ${COLOR.rose}` }} />
            Today
          </span>
          <div style={{ flex: 1 }} />
          <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: COLOR.mute }}>
            WK 1 · {_formatShortDate(weeks[0].date).toUpperCase()} → WK {TIMELINE_WEEKS} · {_formatShortDate(weeks[weeks.length - 1].date).toUpperCase()}
          </span>
        </div>
      </div>
    </div>
  );
}

// ── Main canvas ────────────────────────────────────────────────────────────

export default function JaspenExecutionCanvas({ threadId, bundle, wbs: wbsProp, displayTitle, score, onAskJaspen }) {
  // Local working copy of the WBS. Prefer the explicit wbs prop (fetched
  // from /threads/:tid/wbs which is the authoritative source) over the
  // bundle's project_wbs (which can lag for older threads).
  const initialWbs = wbsProp && Array.isArray(wbsProp.tasks)
    ? wbsProp
    : (bundle?.project_wbs || { name: 'Execution WBS', tasks: [] });
  const [wbs, setWbs] = useState(initialWbs);
  const [view, setView] = useState('list');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const saveTimer = useRef(null);
  const skipNextSave = useRef(true);

  // Sync if the wbs prop or bundle changes (e.g. fresh load).
  // wbsProp wins because /threads/:tid/wbs is the authoritative source.
  useEffect(() => {
    if (wbsProp && Array.isArray(wbsProp.tasks)) {
      skipNextSave.current = true;
      setWbs(wbsProp);
    } else if (bundle?.project_wbs) {
      skipNextSave.current = true;
      setWbs(bundle.project_wbs);
    }
  }, [wbsProp, bundle]);

  // Debounced save on any WBS mutation.
  useEffect(() => {
    if (skipNextSave.current) { skipNextSave.current = false; return; }
    if (!threadId) return;
    if (saveTimer.current) window.clearTimeout(saveTimer.current);
    saveTimer.current = window.setTimeout(async () => {
      try {
        setSaving(true);
        setSaveError(null);
        await Jaspen.upsertThreadWbs(threadId, wbs);
      } catch (e) {
        console.error('[ExecutionCanvas] save failed:', e);
        setSaveError(String(e?.message || e || 'Save failed'));
      } finally {
        setSaving(false);
      }
    }, 600);
    return () => { if (saveTimer.current) window.clearTimeout(saveTimer.current); };
  }, [wbs, threadId]);

  // Group tasks by phase (preserve order of first appearance).
  const phases = useMemo(() => {
    const list = Array.isArray(wbs?.tasks) ? wbs.tasks : [];
    const order = [];
    const byPhase = new Map();
    list.forEach((t) => {
      const name = String(t?.phase || 'Execution').trim() || 'Execution';
      if (!byPhase.has(name)) { order.push(name); byPhase.set(name, []); }
      byPhase.get(name).push(t);
    });
    return order.map((name, idx) => ({
      num: idx + 1,
      title: name,
      weeks: null, // we don't store week ranges yet — show only when present
      tasks: byPhase.get(name),
    }));
  }, [wbs]);

  // Build the owners summary for the header strip.
  const owners = useMemo(() => {
    const counts = new Map();
    (wbs?.tasks || []).forEach((t) => {
      const n = String(t?.owner || t?.suggested_role || '').trim();
      if (!n) return;
      counts.set(n, (counts.get(n) || 0) + 1);
    });
    return Array.from(counts.entries()).map(([name, count]) => ({ name, count }));
  }, [wbs]);

  const updateTask = useCallback((taskId, patch) => {
    setWbs((prev) => {
      const next = { ...(prev || {}) };
      const tasks = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      const idx = tasks.findIndex((t) => String(t?.id || '') === String(taskId));
      if (idx < 0) return prev;
      tasks[idx] = { ...tasks[idx], ...patch };
      next.tasks = tasks;
      return next;
    });
  }, []);

  // Reorder a task within or across phases. Logic:
  //   1. Remove the source from its current position
  //   2. Find the target index (or end-of-phase if no targetId)
  //   3. Insert source at that index, updating its `phase` to match the target
  const reorderTask = useCallback(({ sourceId, targetId, position, targetPhase }) => {
    setWbs((prev) => {
      const tasks = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      const srcIdx = tasks.findIndex((t) => String(t?.id || '') === String(sourceId));
      if (srcIdx < 0) return prev;
      const [moved] = tasks.splice(srcIdx, 1);
      const newPhase = targetPhase || moved.phase || 'Execution';
      moved.phase = newPhase;

      let insertAt = tasks.length;
      if (targetId) {
        const tgtIdx = tasks.findIndex((t) => String(t?.id || '') === String(targetId));
        if (tgtIdx >= 0) insertAt = position === 'before' ? tgtIdx : tgtIdx + 1;
      } else if (position === 'end-of-phase') {
        // Insert at the position immediately after the last task in that phase
        let lastIdxOfPhase = -1;
        tasks.forEach((t, i) => {
          if (String(t?.phase || '').trim() === newPhase) lastIdxOfPhase = i;
        });
        insertAt = lastIdxOfPhase >= 0 ? lastIdxOfPhase + 1 : tasks.length;
      }
      tasks.splice(insertAt, 0, moved);
      return { ...(prev || {}), tasks };
    });
  }, []);

  // Board column drop — moves a task into a new status bucket.
  const onColumnDrop = useCallback((sourceId, newStatus) => {
    setWbs((prev) => {
      const tasks = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      const idx = tasks.findIndex((t) => String(t?.id || '') === String(sourceId));
      if (idx < 0) return prev;
      if (normalizeStatus(tasks[idx]?.status) === newStatus) return prev;
      tasks[idx] = { ...tasks[idx], status: newStatus };
      return { ...(prev || {}), tasks };
    });
  }, []);

  const addTask = useCallback((phaseName) => {
    setWbs((prev) => {
      const next = { ...(prev || {}) };
      const tasks = Array.isArray(prev?.tasks) ? [...prev.tasks] : [];
      tasks.push({
        id: `task_local_${Math.random().toString(36).slice(2, 12)}`,
        title: '',
        description: '',
        priority: 'medium',
        estimated_days: 3,
        timeline_days: 3,
        suggested_role: '',
        owner: '',
        phase: phaseName || 'Execution',
        status: 'todo',
        depends_on: [],
      });
      next.tasks = tasks;
      return next;
    });
  }, []);

  const totalTasks = (wbs?.tasks || []).length;
  const totalPhases = phases.length;

  // ── Hooks must run unconditionally (React rules-of-hooks) ───────────────
  // Anything below the empty-state early return WILL be skipped on the
  // first render when totalTasks === 0, which trips React. So all hooks
  // live up here, ordered identically every render.

  // Priority counts (replaces the owners strip per design feedback) —
  // sums tasks by priority so the user can see the load shape at a glance.
  const priorityCounts = useMemo(() => {
    const all = Array.isArray(wbs?.tasks) ? wbs.tasks : [];
    const counts = { critical: 0, high: 0, medium: 0, low: 0 };
    all.forEach((t) => {
      const p = normalizePriority(t?.priority);
      if (counts[p] !== undefined) counts[p] += 1;
    });
    return counts;
  }, [wbs]);

  // "Updated X min ago" — uses the WBS's own updated_at field if present,
  // otherwise the most recent updated_at across tasks. Refreshes once per minute.
  const [, setNowTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setNowTick((n) => n + 1), 60000);
    return () => clearInterval(id);
  }, []);
  const lastUpdatedLabel = useMemo(() => {
    const tasks = Array.isArray(wbs?.tasks) ? wbs.tasks : [];
    let ts = Date.parse(String(wbs?.updated_at || ''));
    tasks.forEach((t) => {
      const tt = Date.parse(String(t?.updated_at || ''));
      if (Number.isFinite(tt) && (!Number.isFinite(ts) || tt > ts)) ts = tt;
    });
    if (!Number.isFinite(ts)) return null;
    const diffMin = Math.max(0, Math.round((Date.now() - ts) / 60000));
    if (diffMin < 1) return 'Updated just now';
    if (diffMin === 1) return 'Updated 1 min ago';
    if (diffMin < 60) return `Updated ${diffMin} min ago`;
    const hrs = Math.round(diffMin / 60);
    if (hrs === 1) return 'Updated 1 hr ago';
    if (hrs < 24) return `Updated ${hrs} hrs ago`;
    const days = Math.round(hrs / 24);
    return `Updated ${days} day${days === 1 ? '' : 's'} ago`;
  }, [wbs, saving]); // recompute when save completes too

  // Score category label for the badge next to SCORE. (Plain value — not a
  // hook — so its position doesn't matter; kept here for locality.)
  const scoreCategory = typeof score === 'number' && score > 0
    ? (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk')
    : null;

  // Empty state — no execution plan yet. Must come AFTER all hooks.
  if (totalTasks === 0) {
    return (
      <div style={{
        flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center',
        background: COLOR.bg, padding: 48,
      }}>
        <div style={{
          background: '#fff', border: `1px solid ${COLOR.line}`, borderRadius: 14,
          padding: '36px 40px', maxWidth: 560, textAlign: 'center',
          boxShadow: '0 1px 3px rgba(15,23,42,0.04)',
        }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: COLOR.rose, letterSpacing: '0.06em', textTransform: 'uppercase' }}>
            Execution Plan
          </div>
          <div style={{ fontSize: 18, fontWeight: 600, color: COLOR.navy, marginTop: 12 }}>
            No execution plan yet
          </div>
          <div style={{ fontSize: 13, color: COLOR.ink, marginTop: 10, lineHeight: 1.55 }}>
            Head back to Jaspen and ask: <span style={{ color: COLOR.navy, fontWeight: 500 }}>"Build me an execution plan."</span>
            <br />Once it's generated, it shows up here ready to edit.
          </div>
        </div>
      </div>
    );
  }

  return (
    <div style={{
      flex: 1, display: 'flex', flexDirection: 'column',
      background: COLOR.bg, minWidth: 0, overflow: 'hidden',
      fontFamily: "'Inter Tight', system-ui, sans-serif",
    }}>
      {/* Canvas header */}
      <div style={{ padding: '24px 32px 18px', flex: '0 0 auto' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', gap: 18 }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <Eyebrow color={COLOR.rose}>✦ &nbsp;Idea · Trade-off winner</Eyebrow>
            <div style={{ fontSize: 24, fontWeight: 600, color: COLOR.navy, letterSpacing: '-0.018em', marginTop: 8, lineHeight: 1.2 }}>
              {displayTitle || 'Execution plan'}
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10, flexWrap: 'wrap' }}>
              {typeof score === 'number' && score > 0 && (
                <>
                  <span style={{
                    fontFamily: 'JetBrains Mono, monospace',
                    fontSize: 11.5, color: COLOR.navy, padding: '3px 9px',
                    background: COLOR.roseTint, border: `1px solid ${COLOR.roseLine}`,
                    borderRadius: 999, fontWeight: 600,
                  }}>SCORE {score}</span>
                  {scoreCategory && (
                    <span style={{
                      fontFamily: 'JetBrains Mono, monospace',
                      fontSize: 10.5, color: COLOR.greenInk, padding: '3px 8px',
                      background: COLOR.greenTint, borderRadius: 4,
                      letterSpacing: '0.08em', fontWeight: 600, textTransform: 'uppercase',
                    }}>{scoreCategory}</span>
                  )}
                </>
              )}
              <span style={{ fontSize: 13, color: COLOR.ink }}>
                {totalPhases} phase{totalPhases === 1 ? '' : 's'} · {totalTasks} task{totalTasks === 1 ? '' : 's'}
              </span>
              {saving && <span style={{ fontSize: 11.5, color: COLOR.mute }}>Saving…</span>}
              {!saving && saveError && (
                <span style={{ fontSize: 11.5, color: '#dc2626' }} title={saveError}>Save failed — will retry</span>
              )}
              {!saving && !saveError && (
                <span style={{ fontSize: 11.5, color: COLOR.mute, display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  <FontAwesomeIcon icon={faCheck} style={{ fontSize: 9, color: COLOR.green }} /> Saved
                </span>
              )}
            </div>
          </div>
          <ViewSwitcher value={view} onChange={setView} />
        </div>

        {/* Priority counts strip (replaces owners — easier to read load shape) */}
        {totalTasks > 0 && (
          <div style={{
            marginTop: 18, display: 'flex', alignItems: 'center', gap: 10,
            padding: '10px 14px', flexWrap: 'wrap',
            background: '#fff', border: `1px solid ${COLOR.line}`, borderRadius: 12,
          }}>
            <Eyebrow>Priority</Eyebrow>
            {['critical', 'high', 'medium', 'low'].map((p) => {
              const count = priorityCounts[p];
              if (count === 0) return null;
              const sty = PRIORITY_STYLE[p];
              return (
                <div
                  key={p}
                  style={{
                    display: 'inline-flex', alignItems: 'center', gap: 7,
                    padding: '4px 11px', borderRadius: 999,
                    background: COLOR.line2, border: `1px solid ${COLOR.line}`,
                  }}
                >
                  <span style={{ width: 7, height: 7, borderRadius: 4, background: sty.dot }} />
                  <span style={{ fontSize: 12, color: COLOR.navy2, fontWeight: 500 }}>{sty.label}</span>
                  <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: COLOR.mute }}>· {count}</span>
                </div>
              );
            })}
            <div style={{ flex: 1 }} />
            {lastUpdatedLabel && (
              <span style={{ fontFamily: 'JetBrains Mono, monospace', fontSize: 10.5, color: COLOR.mute }}>
                {lastUpdatedLabel}
              </span>
            )}
            {onAskJaspen && (
              <Pill
                tone="ghost"
                onClick={() => onAskJaspen('How can I rebalance task priorities?')}
                style={{ cursor: 'pointer', fontSize: 11.5 }}
              >
                <FontAwesomeIcon icon={faArrowRotateRight} style={{ fontSize: 10 }} />
                Ask Jaspen
              </Pill>
            )}
          </div>
        )}
      </div>

      {/* View body — list / board / timeline */}
      {view === 'list' && (
        <div style={{ flex: 1, overflow: 'auto', padding: '4px 32px 32px' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
            {phases.map((p) => (
              <PhaseCard
                key={p.title}
                phase={p}
                tasks={p.tasks}
                onUpdateTask={updateTask}
                onAddTask={addTask}
                onReorder={reorderTask}
              />
            ))}
          </div>
        </div>
      )}
      {view === 'board' && (
        <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
          <BoardView wbs={wbs} onColumnDrop={onColumnDrop} />
        </div>
      )}
      {view === 'timeline' && (
        <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
          <TimelineView wbs={wbs} phases={phases} />
        </div>
      )}
    </div>
  );
}
