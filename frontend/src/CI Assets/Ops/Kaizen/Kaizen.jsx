// =====================================================
// File: src/Ops/Kaizen/Kaizen.jsx
// =====================================================
import React, { useEffect, useMemo, useState } from 'react';
import styles from './Kaizen.module.css';
import { useNavigate } from 'react-router-dom';
import { useAdminSettings } from '../context/AdminContext';
import ResourcePageWrapper from '../../All/components/ResourcePageWrapper';

/* Route map must match App.js slugs so tool cards navigate correctly. */
const ROUTES = {
  'Project Charter': '/ops/project-charter',
  'SIPOC': '/ops/sipoc',
  'Voice of Customer': '/ops/voice-of-customer',
  'Process Map': '/ops/process-map',
  'Root Cause Analysis': '/ops/root-cause',
  'FMEA': '/ops/fmea',
  'Checksheet': '/ops/checksheet',
  '5 Whys': '/ops/five-whys',
  'Pareto Analysis': '/ops/pareto-analysis',
  'Value Stream Map': '/ops/value-stream',
  'Scatter Plot': '/ops/scatter-plot',
  'Run Chart': '/ops/run-chart',
  'Box Plot': '/ops/box-plot',
  'ANOVA': '/ops/anova',
  'Hypothesis Testing': '/ops/hypothesis-testing',
  'Control Plan': '/ops/control-plan',
  'Standard Work': '/ops/standard-work',
  'Solution Selection': '/ops/solution-selection',
  'Pilot Plan': '/ops/pilot-plan',
  'Implementation Plan': '/ops/implementation-plan',
  'A3': '/ops/a3',
  'Checklists': '/ops/checklists',
  'Data Collection': '/ops/data-collection',
  'Effort-Impact Matrix': '/ops/effort-impact',
  'Gap Analysis': '/ops/gap-analysis',
  'Project Planning': '/ops/project-planning',
  'Sustainment Plan': '/ops/sustainment-plan',
  'DMAIC': '/ops/dmaic',
  'FinY': '/ops/finy',
};

/* ===== Workbook-derived constants (normalized) ===== */
const PRE_EVENT_TEMPLATE = [
  { offsetDays: 21, label: 'Select improvement area and begin Charter for the event.' },
  { offsetDays: 21, label: 'Identify Kaizen Event Leader, Kaizen Facilitator, and team members. Sponsor will notify participants.' },
  { offsetDays: 21, label: 'Prepare a process flow diagram of focus process.' },
  { offsetDays: 21, label: 'Define the action deliverables expected from the Event team.' },
  { offsetDays: 21, label: 'Define the measurements and targets for the team (SQCD).' },
  { offsetDays: 21, label: 'Review deliverables/targets with CI Lead. Decide 4.5 vs 3.5 day Event.' },
  { offsetDays: 21, label: 'Train the Kaizen Event Leader and Sponsor.' },
  { offsetDays: 21, label: 'Document the process (photos, screen captures, video).' },
  { offsetDays: 21, label: 'Create detailed current state flow including wait times.' },
  { offsetDays: 21, label: 'Ask a few hard questions and revisit goals.' },
  { offsetDays: 21, label: 'Why is the process set up the way it is?' },
  { offsetDays: 21, label: 'What is the history of the process and any problem areas?' },
  { offsetDays: 21, label: 'What is average / max volume through the process?' },
  { offsetDays: 21, label: 'Review draft Charter with CI Lead and Process Owner.' },
  { offsetDays: 21, label: 'Invite Controller to end of Day 2 prioritization.' },
  { offsetDays: 21, label: 'Invite IT if solutions likely require programming.' },

  { offsetDays: 14, label: 'Finalize team members and facilitator.' },
  { offsetDays: 14, label: 'Finalize training materials.' },
  { offsetDays: 14, label: 'Pre-event walk-through and stakeholder alignment.' },
  { offsetDays: 14, label: 'Baseline data pull and validation.' },
  { offsetDays: 14, label: 'Room logistics, invites & calendar holds.' },
  { offsetDays: 14, label: 'Update Charter draft and targets.' },
  { offsetDays: 14, label: 'Confirm Sponsor availability for Report-Out.' },
  { offsetDays: 14, label: 'Prep Visual Management boards & prints.' },
  { offsetDays: 14, label: 'Confirm IT involvement (if required).' },
  { offsetDays: 14, label: 'Confirm Controller attendance window.' },
  { offsetDays: 14, label: 'Confirm Safety needs/PPE (if any).' },
  { offsetDays: 14, label: 'Send pre-read packet to participants.' },
  { offsetDays: 14, label: 'Gather materials: flipcharts, stickies, markers, snacks.' },
  { offsetDays: 14, label: 'Event/room access & security cleared.' },
  { offsetDays: 14, label: 'Finalize agenda.' },

  { offsetDays: 7, label: 'Reconfirm schedule commitments with each team member.' },
  { offsetDays: 7, label: 'Complete standard work sheet (flows color coded), if applicable.' },
  { offsetDays: 7, label: "Gather participant ideas of causes and prep preliminary fishbone." },
  { offsetDays: 7, label: 'Be familiar with all tabs in Kaizen Workbook.' },
  { offsetDays: 7, label: 'Finalize Charter.' },
  { offsetDays: 7, label: 'Print Charter & any training handouts.' },
  { offsetDays: 7, label: 'Prep Waste Walk forms (if needed).' },
  { offsetDays: 7, label: 'Validate baseline KPIs & collection method.' },
  { offsetDays: 7, label: 'Remind participants about safety gear (if needed).' },
  { offsetDays: 7, label: 'Confirm all supplies are on hand.' },
  { offsetDays: 7, label: 'Send Day 1 agenda to participants.' },
  { offsetDays: 7, label: 'Final logistics check (room/Teams link).' },
];

const AGENDA_ROWS = [
  { day: '1', begin: '08:00', duration: '30 Min', topic: 'Welcome, Safety & Icebreaker' },
  { day: '1', begin: '08:30', duration: '2:00 Hr', topic: 'Event/Lean Tool Training' },
  { day: '1', begin: '',      duration: '15 Min', topic: 'Break' },
  { day: '1', begin: '10:45', duration: '1:00 Hr', topic: 'Understand Current State / Waste Walk' },
  { day: '1', begin: '',      duration: '1 Hr',    topic: 'Lunch' },
  { day: '1', begin: '',      duration: '2:00 Hr', topic: 'Map Current State / Pain Points' },
  { day: '1', begin: '16:00', duration: '30 Min',  topic: 'Summarize Day One Findings' },
  { day: '1', begin: '16:30', duration: '30 Min',  topic: 'Sponsor Report Out' },

  { day: '2', begin: '08:00', duration: '2:00 Hr', topic: 'Recap & Day 2 Agenda' },
  { day: '2', begin: '',      duration: '1:30 Hr', topic: 'RCA (Fishbone / 5 Whys)' },
  { day: '2', begin: '',      duration: '1:00 Hr', topic: 'Pareto & Data Review' },
  { day: '2', begin: '',      duration: '1 Hr',    topic: 'Lunch' },
  { day: '2', begin: '',      duration: '2:00 Hr', topic: 'Brainstorm / Effort–Impact' },
  { day: '2', begin: '',      duration: '30 Min',  topic: 'Prioritize & Assign Pilots' },

  { day: '3', begin: '08:00', duration: '1:30 Hr', topic: 'Pilot Plans / Standard Work Drafts' },
  { day: '3', begin: '',      duration: '1:00 Hr', topic: 'Implementation Plan' },
  { day: '3', begin: '',      duration: '1:00 Hr', topic: 'Control Plan / Metrics' },
  { day: '3', begin: '',      duration: '1 Hr',    topic: 'Lunch' },
  { day: '3', begin: '',      duration: '1:00 Hr', topic: 'Prepare Report-Out / A3' },
  { day: '3', begin: '15:30', duration: '30 Min',  topic: 'Sponsor Report-Out' },
];

const SUPPLY_LIST = {
  'In-Person': [
    { item: 'Projector', qty: '1' },
    { item: 'Computer', qty: '1' },
    { item: 'Pencils, pads', qty: '20' },
    { item: 'Masking tape', qty: '1' },
    { item: 'Flip chart (stick to the wall)', qty: '2' },
    { item: 'Flip chart markers (4 colors)', qty: '3' },
    { item: 'Posters (Cycle of Change, Agenda, 8 Wastes, etc)', qty: '1' },
    { item: 'Snacks (assortment)', qty: '4' },
    { item: 'Sharpies (4 colors)', qty: '6' },
    { item: 'Post-It Notes (large)', qty: '6' },
    { item: 'Training materials', qty: '8' },
    { item: 'Round color label dots', qty: '1' },
    { item: 'Cleaning supplies', qty: '1' },
    { item: 'Waste Walk printed forms', qty: '20' },
    { item: 'Printed Project Charter', qty: '10' },
    { item: 'Process maps / Baseline data prints', qty: '' },
    { item: 'Prizes', qty: '25' },
    { item: 'Squeeze balls / toys', qty: '10' },
  ],
  'Remote': [
    { item: 'Teams Meeting Scheduled', qty: '1' },
    { item: 'Computer', qty: '1' },
    { item: 'Pencils, pads', qty: '1' },
    { item: 'Template e-copies to team', qty: '1' },
    { item: 'Printable posters (Cycle/Agenda/8 Wastes)', qty: '1' },
    { item: 'Training materials', qty: '1' },
    { item: 'Waste Walk forms', qty: '1' },
    { item: 'Project Charter (PDF)', qty: '1' },
  ],
};

/* ===== Utils ===== */
const fmt = (d) => (d ? new Date(d).toISOString().slice(0, 10) : '');
const addDays = (dateStr, n) => {
  const d = new Date(dateStr);
  d.setDate(d.getDate() + n);
  return fmt(d);
};
const subDays = (dateStr, n) => addDays(dateStr, -n);

/* Small UI helpers */
const PhaseBadge = ({ n, label, active, onClick }) => (
  <button className={`${styles.stepperItem} ${active ? styles.active : ''}`} onClick={onClick}>
    <div className={styles.stepperNode}>
      <div className={styles.stepNumber}>{n}</div>
      <div className={styles.stepLabel}>{label}</div>
    </div>
  </button>
);
const ToolCard = ({ icon, name, onClick, status = 'Not Started' }) => (
  <button className={styles.toolCard} onClick={onClick} title={name}>
    <div className={styles.toolIcon}><i className={icon} /></div>
    <div className={styles.toolInfo}>
      <h4>{name}</h4>
      <p>Open {name}</p>
      <div className={styles.toolStatus}>
        <span className={styles.statusBadge}>{status}</span>
      </div>
    </div>
  </button>
);

const Kaizen = () => {
  const navigate = useNavigate();
  const { adminSettings } = useAdminSettings();

  // Make Kii state clearly Kaizen-specific
  useEffect(() => {
    try {
      document.documentElement.setAttribute('data-kii-context', 'kaizen-event');
      document.documentElement.setAttribute('data-kii-title', 'Kaizen Event');
      window.__kiiContext = {
        page: 'Kaizen Blitz',
        tool: 'Kaizen Event',
        intent: 'Help plan and facilitate a Kaizen workshop (pre-work, Day 1–3, report-out, follow-up).'
      };
      window.dispatchEvent(new CustomEvent('kii:set-context', { detail: window.__kiiContext }));
    } catch (e) { /* no-op if not supported */ }
  }, []);

  /* Local admin overlay (non-persistent) */
  const defaults = { enableSave: true, enableExport: true, enableApprovals: false };
  const [adminModalOpen, setAdminModalOpen] = useState(false);
  const [adminLocal, setAdminLocal] = useState(defaults);
  const effectiveAdmin = useMemo(
    () => ({ ...defaults, ...(adminSettings || {}), ...(adminLocal || {}) }),
    [adminSettings, adminLocal]
  );

  /* Phases */
  const phases = [
    { id: 'prework', name: 'Pre-Work', order: 1 },
    { id: 'day1', name: 'Day 1', order: 2 },
    { id: 'day2', name: 'Day 2', order: 3 },
    { id: 'day3', name: 'Day 3', order: 4 },
    { id: 'report', name: 'Report-Out', order: 5 },
    { id: 'followup', name: 'Follow-Up', order: 6 },
  ];
  const [currentPhase, setCurrentPhase] = useState('prework');

  /* Workshop & Pre-work */
  const [workshopDate, setWorkshopDate] = useState(fmt(new Date()));
  const [preWorkStart, setPreWorkStart] = useState(subDays(workshopDate, 21));
  const [preEventTasks, setPreEventTasks] = useState([]);
  const [eventMode, setEventMode] = useState('In-Person');

  const regenerateDates = (wDate = workshopDate) => {
    if (!wDate) return;
    setPreWorkStart(subDays(wDate, 21));
    setPreEventTasks(
      PRE_EVENT_TEMPLATE.map((t, i) => ({
        id: i + 1,
        label: t.label,
        due: t.offsetDays ? subDays(wDate, t.offsetDays) : '',
        done: false,
      }))
    );
  };
  useEffect(() => { regenerateDates(workshopDate); }, []); // init

  const completionPct = useMemo(() => {
    const total = preEventTasks.length || 1;
    const done = preEventTasks.filter((t) => t.done).length;
    return Math.round((done / total) * 100);
  }, [preEventTasks]);
  const onToggleTask = (id) =>
    setPreEventTasks((prev) => prev.map((t) => (t.id === id ? { ...t, done: !t.done } : t)));

  /* Downloads (client CSV) */
  const downloadCSV = (rows, filename, headers) => {
    const header = headers.join(',');
    const body = rows
      .map((r) =>
        headers
          .map((h) => {
            const val = r[h] ?? '';
            const s = String(val).replace(/"/g, '""');
            return /[,\"\n]/.test(s) ? `"${s}"` : s;
          })
          .join(',')
      )
      .join('\n');
    const csv = [header, body].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  };
  const downloadAgenda = () => {
    const rows = AGENDA_ROWS.map((r) => ({ Day: r.day, Begin: r.begin, Duration: r.duration, Topic: r.topic }));
    downloadCSV(rows, 'Kaizen_Agenda.csv', ['Day', 'Begin', 'Duration', 'Topic']);
  };
  const downloadSupplies = () => {
    const rows = (SUPPLY_LIST[eventMode] || []).map((r) => ({ Item: r.item, Qty: r.qty }));
    downloadCSV(rows, `Kaizen_Supplies_${eventMode.replace(/\s+/g, '')}.csv`, ['Item', 'Qty']);
  };

  /* Phase tools (wired) */
  const openTool = (name) => { const p = ROUTES[name]; if (p) navigate(p); };
  const day1Tools = [
    { name: 'Checksheet', icon: 'fas fa-clipboard-check' },
    { name: 'Process Map', icon: 'fas fa-project-diagram' },
    { name: 'Value Stream Map', icon: 'fas fa-stream' },
    { name: 'Root Cause Analysis', icon: 'fas fa-search' },
    { name: '5 Whys', icon: 'fas fa-question-circle' },
    { name: 'Pareto Analysis', icon: 'fas fa-chart-bar' },
  ];
  const day2Tools = [
    { name: 'Effort-Impact Matrix', icon: 'fas fa-th-large' },
    { name: 'Solution Selection', icon: 'fas fa-tasks' },
    { name: 'Pilot Plan', icon: 'fas fa-rocket' },
    { name: 'Standard Work', icon: 'fas fa-clipboard-check' },
  ];
  const day3Tools = [
    { name: 'Implementation Plan', icon: 'fas fa-route' },
    { name: 'Control Plan', icon: 'fas fa-shield-alt' },
    { name: 'Project Planning', icon: 'fas fa-calendar-alt' },
    { name: 'Checklists', icon: 'fas fa-list' },
  ];
  const reportTools = [
    { name: 'A3', icon: 'fas fa-file-alt' },
    { name: 'Project Charter', icon: 'fas fa-file-contract' },
    { name: 'FinY', icon: 'fas fa-dollar-sign' },
  ];
  const followUpTools = [
    { name: 'Sustainment Plan', icon: 'fas fa-leaf' },
    { name: 'Control Plan', icon: 'fas fa-sliders-h' },
    { name: 'Data Collection', icon: 'fas fa-database' },
    { name: 'Run Chart', icon: 'fas fa-wave-square' },
    { name: 'Control Chart', icon: 'fas fa-chart-line' },
  ];

  const isAdmin = !!(adminSettings?.isAdmin || adminSettings?.role === 'admin');

  return (
    <ResourcePageWrapper pageName="Kaizen Blitz" toolName="Kaizen Event" adminSettings={adminSettings}>
      <div className={styles.kaizen}>
        {/* Compact Header */}
        <div className={styles.header}>
          <div className={styles.headerTop}>
            <div className={styles.projectTitle}>
              <h1>Kaizen Blitz</h1>
              <div className={styles.subtitle}><span>Workshop</span> <span className={styles.dot}>•</span> <span>Rapid Improvement Event</span></div>
            </div>

            <div className={styles.planningBar} role="group" aria-label="Kaizen planning">
              <div className={styles.fieldSm}>
                <label>Workshop Date</label>
                <input
                  type="date"
                  className={styles.inputSm}
                  value={workshopDate}
                  onChange={(e) => { const val = e.target.value; setWorkshopDate(val); regenerateDates(val); }}
                />
              </div>

              <div className={styles.fieldSm}>
                <label>Pre-Work starts</label>
                <input type="text" className={styles.inputSm} value={preWorkStart} readOnly />
              </div>

              <div className={styles.barActions}>
                <button className={`${styles.btnSm} ${styles.btnSecondary}`} onClick={() => regenerateDates()}>
                  <i className="fas fa-sync-alt" /> Regenerate
                </button>
                {effectiveAdmin.enableSave && (
                  <button className={`${styles.btnSm} ${styles.btnDark}`}><i className="fas fa-save" /> Save</button>
                )}
                {effectiveAdmin.enableExport && (
                  <button className={`${styles.btnSm} ${styles.btnPrimary}`}><i className="fas fa-download" /> Export</button>
                )}
                {isAdmin && (
                  <button className={`${styles.btnIcon}`} onClick={() => setAdminModalOpen(true)} title="Admin Settings">
                    <i className="fas fa-cog" />
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>

        {/* Phase Stepper */}
        <div className={styles.phaseStepper}>
          <div className={styles.stepperContainer}>
            {phases.map((p) => (
              <PhaseBadge
                key={p.id}
                n={p.order}
                label={p.name}
                active={currentPhase === p.id}
                onClick={() => setCurrentPhase(p.id)}
              />
            ))}
          </div>

          <div className={styles.progressSummary}>
            <div className={styles.progressBar}><div className={styles.progressFill} style={{ width: `${completionPct}%` }} /></div>
            <span className={styles.progressText}>{completionPct}% Pre-Work Complete</span>
          </div>
        </div>

        {/* Main Content */}
        <div className={styles.mainContent}>
          {/* ===== PRE-WORK ===== */}
          {currentPhase === 'prework' && (
            <div className={styles.phaseContent}>

              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}>
                  <h3>Pre-Event Checklist</h3>
                </div>

                <div className={styles.deliverablesList}>
                  {preEventTasks.length === 0 ? (
                    <div className={styles.emptyState}>Pick a workshop date to generate your pre-work.</div>
                  ) : (
                    preEventTasks.map((t) => (
                      <label key={t.id} className={styles.deliverable}>
                        <input type="checkbox" checked={!!t.done} onChange={() => onToggleTask(t.id)} />
                        <div className={styles.deliverableBody}>
                          <div className={styles.taskLabel}>{t.label}</div>
                          <div className={styles.taskMeta}>Due: {t.due || '—'}</div>
                        </div>
                      </label>
                    ))
                  )}
                </div>
              </div>

              {/* Agenda & Supplies */}
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}>
                  <h3>Agenda & Supplies</h3>
                </div>

                <div className={styles.twoCol}>
                  {/* Agenda Panel */}
                  <div className={styles.panelCard}>
                    <div className={styles.panelHeader}>
                      <div>
                        <div className={styles.panelTitle}>Agenda (Days 1–3)</div>
                        <div className={styles.panelHint}>Prefilled sample agenda from workbook</div>
                      </div>
                      <div className={styles.panelActions}>
                        <button className={`${styles.btnXs} ${styles.btnGhost}`} onClick={downloadAgenda}>
                          <i className="fas fa-file-csv" /> CSV
                        </button>
                      </div>
                    </div>

                    <div className={styles.panelBodyScroll}>
                      {AGENDA_ROWS.map((a, i) => (
                        <div key={i} className={styles.rowLine}>
                          <div className={styles.badge}>Day {a.day}</div>
                          <div className={styles.rowMid}>
                            <div className={styles.rowTitle}>{a.topic}</div>
                            <div className={styles.rowSub}>
                              {a.begin || '—'} • {a.duration}
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Supplies Panel */}
                  <div className={styles.panelCard}>
                    <div className={styles.panelHeader}>
                      <div className={styles.panelTitle}>Supply List</div>
                      <div className={styles.panelActions} style={{ gap: 8 }}>
                        <select className={styles.inputXs} value={eventMode} onChange={(e) => setEventMode(e.target.value)}>
                          <option>In-Person</option>
                          <option>Remote</option>
                        </select>
                        <button className={`${styles.btnXs} ${styles.btnGhost}`} onClick={downloadSupplies}>
                          <i className="fas fa-file-csv" /> CSV
                        </button>
                      </div>
                    </div>

                    <div className={styles.panelBodyScroll}>
                      {(SUPPLY_LIST[eventMode] || []).map((s, i) => (
                        <div key={i} className={styles.rowLine}>
                          <div className={styles.dotBullet} />
                          <div className={styles.rowMid}>
                            <div className={styles.rowTitle}>{s.item}</div>
                          </div>
                          {s.qty ? <div className={styles.qtyPill}>Qty {s.qty}</div> : null}
                        </div>
                      ))}
                    </div>
                  </div>
                </div>
              </div>

            </div>
          )}

          {/* ===== DAY 1 ===== */}
          {currentPhase === 'day1' && (
            <div className={styles.phaseContent}>
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}><h3>Day 1 — Understand Current State</h3></div>
                <div className={styles.toolsGrid}>
                  {day1Tools.map((t) => <ToolCard key={t.name} icon={t.icon} name={t.name} onClick={() => openTool(t.name)} />)}
                </div>
              </div>
            </div>
          )}

          {/* ===== DAY 2 ===== */}
          {currentPhase === 'day2' && (
            <div className={styles.phaseContent}>
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}><h3>Day 2 — Analyze & Prioritize</h3></div>
                <div className={styles.toolsGrid}>
                  {day2Tools.map((t) => <ToolCard key={t.name} icon={t.icon} name={t.name} onClick={() => openTool(t.name)} />)}
                </div>
              </div>
            </div>
          )}

          {/* ===== DAY 3 ===== */}
          {currentPhase === 'day3' && (
            <div className={styles.phaseContent}>
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}><h3>Day 3 — Implement & Control</h3></div>
                <div className={styles.toolsGrid}>
                  {day3Tools.map((t) => <ToolCard key={t.name} icon={t.icon} name={t.name} onClick={() => openTool(t.name)} />)}
                </div>
              </div>
            </div>
          )}

          {/* ===== REPORT-OUT ===== */}
          {currentPhase === 'report' && (
            <div className={styles.phaseContent}>
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}><h3>Report-Out</h3></div>
                <div className={styles.toolsGrid}>
                  {reportTools.map((t) => <ToolCard key={t.name} icon={t.icon} name={t.name} onClick={() => openTool(t.name)} />)}
                </div>
              </div>
            </div>
          )}

          {/* ===== FOLLOW-UP ===== */}
          {currentPhase === 'followup' && (
            <div className={styles.phaseContent}>
              <div className={styles.section}>
                <div className={styles.sectionHeaderRow}><h3>Follow-Up</h3></div>
                <div className={styles.toolsGrid}>
                  {followUpTools.map((t) => <ToolCard key={t.name} icon={t.icon} name={t.name} onClick={() => openTool(t.name)} />)}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Admin Settings Modal (local only) */}
        {adminModalOpen && (
          <div className={styles.modal}>
            <div className={styles.modalContent}>
              <div className={styles.modalHeader}>
                <h3>Admin Settings</h3>
                <button className={styles.closeBtn} onClick={() => setAdminModalOpen(false)}><i className="fas fa-times" /></button>
              </div>
              <div className={styles.modalBody}>
                <label className={styles.adminRow}>
                  <input type="checkbox" checked={!!adminLocal.enableSave} onChange={(e) => setAdminLocal((s) => ({ ...s, enableSave: e.target.checked }))} />
                  Enable Save
                </label>
                <label className={styles.adminRow}>
                  <input type="checkbox" checked={!!adminLocal.enableExport} onChange={(e) => setAdminLocal((s) => ({ ...s, enableExport: e.target.checked }))} />
                  Enable Export
                </label>
                <label className={styles.adminRow}>
                  <input type="checkbox" checked={!!adminLocal.enableApprovals} onChange={(e) => setAdminLocal((s) => ({ ...s, enableApprovals: e.target.checked }))} />
                  Enable Approvals
                </label>
                <p className={styles.note}>Local only. To persist org-wide, update AdminContext provider.</p>
              </div>
              <div className={styles.modalFooter}>
                <button className={styles.confirmBtn} onClick={() => setAdminModalOpen(false)}>Done</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </ResourcePageWrapper>
  );
};

export default Kaizen;
