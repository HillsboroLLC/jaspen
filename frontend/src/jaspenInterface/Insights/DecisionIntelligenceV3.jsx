import React, { useEffect, useMemo, useRef, useState } from 'react';
import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';
import './DecisionIntelligenceV3.css';

const STATES = {
  pursued: 'Pursued', not_pursued: 'Not pursued', open: 'Open', archived: 'Archived',
};
const safe = (value) => (Array.isArray(value) ? value : []);
const metricValue = (metric) => metric?.value == null ? '—' : metric.value;
// A date-only value (YYYY-MM-DD) is a calendar date, never shifted by time zone.
const parseDate = (value) => (/^\d{4}-\d{2}-\d{2}$/.test(String(value)) ? new Date(`${value}T00:00:00`) : new Date(value));
const formatDate = (value) => value ? parseDate(value).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '—';
const formatDuration = (hours) => hours == null ? '—' : hours < 1 ? `${Math.max(1, Math.round(hours * 60))} min` : hours < 24 ? `${Math.round(hours)} hr` : `${Math.round(hours / 24)} days`;

const TRIGGER_TITLES = {
  decision_milestone_at_risk: 'Decision milestone at risk',
  failed_required_check_without_task: 'Pursuing against a failed required check',
  committed_task_overdue: 'Committed task overdue',
  blocked_by_overdue_commitment: 'Blocked by an overdue commitment',
  outcome_review_due: 'Review due',
  condition_past_due: 'Condition past due',
};
const listLabels = (items) => safe(items).map((item) => item.label || item.key).filter(Boolean).join(', ');
// Deterministic labels composed from stored facts; the backend sends no prose.
export function triggerLabel(trigger) {
  const e = trigger?.evidence || {};
  switch (trigger?.kind) {
    case 'decision_milestone_at_risk': {
      const n = safe(e.required_checks).length;
      return `Deadline ${formatDate(e.deadline)} is within ${e.window_days} days and ${n} required check${n === 1 ? ' isn’t' : 's aren’t'} confirmed: ${listLabels(e.required_checks)}.`;
    }
    case 'failed_required_check_without_task':
      return `Pursued with a failed required check (${e.gate_label || e.gate_key}) and no plan task addressing it.`;
    case 'committed_task_overdue':
      return `“${e.task_name || 'Committed task'}” was due ${formatDate(e.current_due_date)}${e.committed_due_date && e.committed_due_date !== e.current_due_date ? ` (first committed for ${formatDate(e.committed_due_date)})` : ''} and isn’t done.`;
    case 'blocked_by_overdue_commitment':
      return `“${e.task_name || 'A task'}” is waiting on an overdue committed task.`;
    case 'outcome_review_due':
      return `The review date ${formatDate(e.review_by)} has passed with no outcome recorded${e.measure ? ` for “${e.measure}”` : ''}.`;
    case 'condition_past_due':
      return `The condition “${e.condition}” was due ${formatDate(e.due_by)} and is still open.`;
    default:
      return '';
  }
}
const CONDITION_STATUS = { open: 'open', met: 'met', not_met: 'not met', waived: 'waived' };
function OptionMarkers({ item }) {
  const conditions = safe(item.conditions);
  const open = conditions.filter((condition) => condition.status === 'open').length;
  return <>{conditions.length > 0 && <span className="di3-tag">{open ? `Conditional · ${open} open` : 'Conditions settled'}</span>}{item.against_recommendation && <span className="di3-tag is-warning">Against Jaspen’s {item.against_recommendation.jaspen_recommendation || 'recommendation'}</span>}</>;
}
const OUTCOME_STAGES = [
  ['success_measure_captured', 'Success measure captured'],
  ['implementation_complete', 'Implementation complete'],
  ['awaiting_measurement', 'Awaiting measurement'],
  ['measured', 'Measured'],
  ['met_expectation', 'Met expectation'],
  ['lessons', 'Lessons recorded'],
];

function EmptyChart({ type = 'bars', children }) {
  return <div className={`di3-placeholder di3-placeholder--${type}`}><div aria-hidden="true" className="di3-placeholder-art"><i /><i /><i /><i /></div><p>{children}</p></div>;
}

function BarRows({ rows, max, labelKey = 'label', valueKey = 'value' }) {
  return <div className="di3-bars">{rows.map((row) => <div className="di3-bar" key={`${row[labelKey]}:${row[valueKey]}`}><span>{row[labelKey]}</span><span className="di3-track"><i style={{ width: `${max ? (row[valueKey] / max) * 100 : 0}%` }} /></span><b>{row[valueKey]}</b></div>)}</div>;
}

function SummaryFinding({ finding, onFilter }) {
  if (finding.kind === 'exception') return <div className="di3-finding"><p><span className="di3-tag is-danger">Exception</span><b>{finding.count} scored option{finding.count === 1 ? '' : 's'}</b> need attention now because a stored condition triggered.</p><button type="button" onClick={() => onFilter('attention', true)}>Show these</button></div>;
  if (finding.kind === 'pattern' && finding.pattern === 'recurring_gap') return <div className="di3-finding"><p><span className="di3-tag is-warning">Pattern</span><b>{finding.label}</b> was a gap in {finding.decisions_affected} of {finding.decisions_total} {finding.decision_kind} decisions.</p><button type="button" onClick={() => onFilter('gap', finding.gap_key)}>Show these</button></div>;
  if (finding.kind === 'improvement') return <div className="di3-finding"><p><span className="di3-tag is-success">Improvement</span>Evidence at commitment moved from <b>{finding.from_pct}%</b> ({finding.from_month}) to <b>{finding.to_pct}%</b> ({finding.to_month}).</p></div>;
  if (finding.kind === 'pattern') return <div className="di3-finding"><p><span className="di3-tag is-warning">Pattern</span><b>{finding.count} of {finding.total}</b> pursued options were under 50% evidence-backed when committed.</p><button type="button" onClick={() => onFilter('state', 'pursued')}>Show pursued</button></div>;
  return <div className="di3-finding"><p><span className="di3-tag">Follow-through</span>Of <b>{finding.identified}</b> gaps accepted at commitment, {finding.tasks_completed} have a completed task and {finding.resolved} are resolved by evidence.</p><a href="#di3-plans">Show plans</a></div>;
}

function MetricCard({ label, definition, metric, active, onClick, detail }) {
  const Component = onClick ? 'button' : 'div';
  return <Component type={onClick ? 'button' : undefined} className={`di3-kpi${active ? ' is-active' : ''}`} onClick={onClick} aria-pressed={onClick ? active : undefined}><strong>{metricValue(metric)}</strong><b>{label}</b><span>{definition}</span>{detail && <small>{detail}</small>}</Component>;
}

function StageBars({ stages }) {
  const rows = Object.entries(stages || {}).map(([key, value]) => ({ label: key.replaceAll('_', ' '), value: Number(value || 0) }));
  return rows.length ? <BarRows rows={rows} max={Math.max(...rows.map((row) => row.value), 1)} /> : null;
}

function FlowLines({ points }) {
  const max = Math.max(...points.flatMap((point) => [point.scored, point.decided]), 1);
  const coords = (key) => points.map((point, index) => `${points.length === 1 ? 50 : (index / (points.length - 1)) * 100},${36 - (point[key] / max) * 32}`).join(' ');
  const label = points.map((point) => `${formatDate(point.date)}: ${point.scored} scored, ${point.decided} decided`).join('; ');
  return <div className="di3-lines" role="img" aria-label={label}><svg viewBox="0 0 100 40" preserveAspectRatio="none" aria-hidden="true"><polyline className="is-scored" points={coords('scored')} /><polyline className="is-decided" points={coords('decided')} /></svg><div className="di3-line-labels">{points.map((point) => <span key={point.date}>{formatDate(point.date)}<b>{point.scored} scored · {point.decided} decided</b></span>)}</div></div>;
}

export default function DecisionIntelligenceV3({ navigate }) {
  const stored = useMemo(() => { try { return JSON.parse(localStorage.getItem('jaspen:insights:v3') || '{}'); } catch (_) { return {}; } }, []);
  const [scope, setScope] = useState(stored.scope || 'organization');
  const [filters, setFilters] = useState({ days: '', state: '', kind: '', member: '', search: '', attention: false, ...(stored.filters || {}) });
  const [page, setPage] = useState(stored.page || 1);
  const [expanded, setExpanded] = useState(stored.expanded || '');
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [updated, setUpdated] = useState(null);
  const generation = useRef(0);
  const hasLoaded = useRef(false);

  const query = useMemo(() => {
    const params = new URLSearchParams({ scope, page: String(page), per_page: '25' });
    Object.entries(filters).forEach(([key, value]) => { if (value) params.set(key, String(value)); });
    return params.toString();
  }, [filters, page, scope]);

  useEffect(() => {
    try { localStorage.setItem('jaspen:insights:v3', JSON.stringify({ scope, filters, page, expanded })); } catch (_) { /* optional */ }
  }, [expanded, filters, page, scope]);

  useEffect(() => {
    const current = ++generation.current;
    let active = true;
    let controller;
    let timer;
    const load = async (initial = false) => {
      controller?.abort(); controller = new AbortController();
      if (initial) setLoading(true);
      try {
        const response = await fetch(`${API_BASE}/api/v1/insights/overview?${query}`, { headers: buildAuthHeaders({}, 'GET'), credentials: 'include', signal: controller.signal });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(payload.error || 'Unable to load Insights.');
        if (active && generation.current === current) { setData(payload); setError(''); setUpdated(Date.now()); hasLoaded.current = true; if (payload.scope !== scope) setScope(payload.scope); }
      } catch (reason) {
        if (active && reason?.name !== 'AbortError' && initial) setError(reason.message || 'Unable to load Insights.');
      } finally { if (active && initial) setLoading(false); }
    };
    const refresh = () => { if (document.visibilityState === 'visible') load(false); };
    load(!hasLoaded.current); timer = window.setInterval(refresh, 60000); window.addEventListener('focus', refresh);
    return () => { active = false; controller?.abort(); window.clearInterval(timer); window.removeEventListener('focus', refresh); };
  }, [query, scope]);

  const setFilter = (key, value) => { setFilters((current) => ({ ...current, [key]: value })); setPage(1); };
  const clear = () => { setFilters({ days: '', state: '', kind: '', member: '', search: '', attention: false }); setPage(1); };
  const activity = data?.activity || {};
  const effect = data?.effectiveness || {};
  const register = data?.register || { rows: [], total: 0, page: 1, pages: 1 };
  const rows = safe(register.rows);
  const chips = Object.entries(filters).filter(([, value]) => value).map(([key, value]) => ({ key, label: key === 'state' ? STATES[value] : key === 'attention' ? 'Needs attention' : String(value) }));

  if (loading) return <section className="di3-state" role="status">Loading your decision work…</section>;
  if (error) return <section className="di3-state is-error" role="alert">{error}</section>;

  const counts = ['pursued', 'not_pursued', 'open', 'archived'].map((key) => Number(activity[key]?.value || 0));
  const total = Number(activity.total_scored?.value || 0);
  const attention = safe(activity.needs_attention);
  const time = activity.average_time_to_plan_hours;
  const recurring = safe(effect.recurring_gaps).sort((a, b) => b.decisions_affected - a.decisions_affected).slice(0, 6);
  const evidencePoints = safe(effect.evidence_at_commitment?.points);

  return <section className="di3" aria-labelledby="di3-title">
    <header className="di3-head"><div><p className="di3-kicker">Insights</p><h2 id="di3-title">{data?.scope === 'organization' ? 'Organization decision work' : 'Your decision work'}</h2><small>{updated ? 'Updated live · last refresh just now' : ''}</small></div>{data?.show_scope_control && <div className="di3-segment" role="group" aria-label="Insights scope"><button type="button" aria-pressed={scope === 'mine'} onClick={() => setScope('mine')}>My activity</button><button type="button" aria-pressed={scope === 'organization'} onClick={() => setScope('organization')}>Organization</button></div>}</header>

    <div className="di3-filters" role="search"><select aria-label="First scored" value={filters.days} onChange={(event) => setFilter('days', event.target.value)}><option value="">All time</option><option value="30">First scored in the last 30 days</option><option value="14">First scored in the last 14 days</option></select><select aria-label="State" value={filters.state} onChange={(event) => setFilter('state', event.target.value)}><option value="">Any state</option>{Object.entries(STATES).map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select><select aria-label="Kind of decision" value={filters.kind} onChange={(event) => setFilter('kind', event.target.value)}><option value="">All kinds</option>{safe(data?.facets?.kinds).map((kind) => <option key={kind}>{kind}</option>)}</select>{data?.show_scope_control && scope === 'organization' && <select aria-label="Member" value={filters.member} onChange={(event) => setFilter('member', event.target.value)}><option value="">All members</option>{safe(data?.facets?.members).map((member) => <option value={member.id} key={member.id}>{member.name}</option>)}</select>}<input aria-label="Search options and decisions" type="search" placeholder="Search options and decisions" value={filters.search} onChange={(event) => setFilter('search', event.target.value)} /></div>
    {chips.length > 0 && <div className="di3-chips">{chips.map((chip) => <button type="button" key={chip.key} onClick={() => setFilter(chip.key, chip.key === 'attention' ? false : '')} aria-label={`Remove filter ${chip.label}`}>{chip.label} ×</button>)}<button type="button" className="is-link" onClick={clear}>Clear filters</button></div>}

    <section className="di3-section"><div className="di3-section-title"><h3>Summary</h3><span>Exceptions, patterns and improvements in your work, each with a next step</span></div>{safe(data?.summary).length ? safe(data.summary).map((finding, index) => <SummaryFinding key={`${finding.kind}:${index}`} finding={finding} onFilter={setFilter} />) : <p className="di3-muted">{total ? 'Nothing needs attention, and no supported pattern stands out yet.' : 'No scored options match these filters.'}</p>}</section>

    <section className="di3-section"><div className="di3-section-title"><h3>Activity</h3><span>What has been evaluated, what you’re pursuing, how the work is moving, and where it needs you</span></div><div className="di3-kpis"><MetricCard label="Total scored" definition="Distinct options evaluated. Rescoring doesn’t add one." metric={activity.total_scored} /><MetricCard label="Pursued" definition="Options you’re moving forward with" metric={activity.pursued} active={filters.state === 'pursued'} onClick={() => setFilter('state', filters.state === 'pursued' ? '' : 'pursued')} /><MetricCard label="Not pursued" definition="Options you decided against" metric={activity.not_pursued} active={filters.state === 'not_pursued'} onClick={() => setFilter('state', filters.state === 'not_pursued' ? '' : 'not_pursued')} /><MetricCard label="Open" definition="Still under consideration" metric={activity.open} active={filters.state === 'open'} onClick={() => setFilter('state', filters.state === 'open' ? '' : 'open')} /><MetricCard label="Archived" definition="Removed without a decision" metric={activity.archived} active={filters.state === 'archived'} onClick={() => setFilter('state', filters.state === 'archived' ? '' : 'archived')} /></div>
      {total > 0 && <><div className="di3-reconcile" role="img" aria-label={`Pursued ${counts[0]}, not pursued ${counts[1]}, open ${counts[2]}, archived ${counts[3]}`}>{counts.map((count, index) => count > 0 && <i key={index} className={`s${index}`} style={{ flex: count }} />)}</div><p className="di3-legend">Pursued {counts[0]} · Not pursued {counts[1]} · Open {counts[2]} · Archived {counts[3]} = {total} scored</p></>}
      <div className="di3-grid2"><article className="di3-card"><h4>Needs attention</h4><p className="di3-muted">Exceptions with a clear trigger, the evidence behind it, and a next step</p>{attention.length ? attention.map((item) => <button type="button" className="di3-exception" key={item.id} onClick={() => setExpanded(item.id)}><span className="di3-tag is-danger">Now</span><span><b>{item.option_name}</b><small>{TRIGGER_TITLES[item.triggers[0]?.kind]}: {triggerLabel(item.triggers[0])}</small></span></button>) : <p className="di3-muted">No exceptions right now. Open options and ordinary gaps aren’t exceptions.</p>}</article><article className="di3-card"><h4>Average time to plan</h4><p className="di3-muted">From an option’s first scorecard to its first execution plan</p>{time?.value == null ? <EmptyChart>Once you build a plan for a scored option, the time to that plan will show here.</EmptyChart> : <><strong className="di3-big">{formatDuration(time.value)}</strong><p>{time.within_one_hour} of {time.coverage} planned within an hour of scoring.</p></>}</article></div>
      <div className="di3-grid2"><article className="di3-card"><h4>Evaluation and decisions over time</h4><p className="di3-muted">Options scored and decided, on their own event dates</p>{safe(activity.flow).length > 1 ? <FlowLines points={safe(activity.flow)} /> : <EmptyChart type="line">Options scored and options decided each week will show here as two lines.</EmptyChart>}</article><article className="di3-card"><h4>By kind of decision</h4><p className="di3-muted">Which kinds reach a decision, and how quickly</p>{safe(activity.by_kind).length ? <div className="di3-tablewrap"><table><thead><tr><th>Kind</th><th>Scored</th><th>Pursued</th><th>Not pursued</th><th>Open</th></tr></thead><tbody>{activity.by_kind.map((item) => <tr key={item.kind}><td>{item.kind}</td><td>{item.scored}</td><td>{item.pursued}</td><td>{item.not_pursued}</td><td>{item.open}</td></tr>)}</tbody></table></div> : <EmptyChart>Decision kinds will appear here.</EmptyChart>}</article></div>
      <article className="di3-card" id="di3-plans"><h4>Plans in execution</h4><p className="di3-muted">How execution is going for the options you’re pursuing</p>{safe(activity.plans).length ? <div className="di3-tablewrap"><table><thead><tr><th>Option</th><th>Decision</th><th>Progress</th><th>Gaps</th></tr></thead><tbody>{activity.plans.map((item) => <tr key={item.id}><td>{item.option_name}</td><td>{item.decision_title}</td><td><span className="di3-progress"><i style={{ width: `${item.plan.tasks_total ? item.plan.tasks_completed / item.plan.tasks_total * 100 : 0}%` }} /></span>{item.plan.tasks_completed} of {item.plan.tasks_total}</td><td>{safe(item.gaps).length}</td></tr>)}</tbody></table></div> : <EmptyChart type="list">Each execution plan will show here with its progress.</EmptyChart>}</article>
    </section>

    <section className="di3-section"><div className="di3-section-title"><h3>Effectiveness</h3><span>How well-founded the work you act on is, whether its gaps get resolved, and what it produces</span></div><div className="di3-grid2"><article className="di3-card"><h4>What you’re acting on</h4><p className="di3-muted">Strength and evidence at the moment you committed</p>{safe(effect.acting_on).some((row) => row.total) ? <div className="di3-tablewrap"><table><thead><tr><th>State</th><th>Score bands</th><th>Mostly assumed</th></tr></thead><tbody>{effect.acting_on.map((row) => <tr key={row.state}><td>{STATES[row.state]}</td><td>{Object.entries(row.bands || {}).map(([key, value]) => `${key} ${value}`).join(' · ') || 'None'}</td><td>{row.mostly_assumed} of {row.total}</td></tr>)}</tbody></table></div> : <EmptyChart>Once you pursue an option, its strength and evidence will show here.</EmptyChart>}</article><article className="di3-card"><h4>Gap follow-through</h4><p className="di3-muted">Each stage is a separate stored event</p>{effect.gap_follow_through?.identified ? <StageBars stages={effect.gap_follow_through} /> : <EmptyChart>What happens to gaps after commitment will show here.</EmptyChart>}</article></div>
      <div className="di3-grid2"><article className="di3-card"><h4>Evidence at commitment over time</h4><p className="di3-muted">Are the options you act on getting better evidenced?</p>{effect.evidence_at_commitment?.value ? <><BarRows rows={effect.evidence_at_commitment.value.map((point) => ({ label: `${point.month} · n ${point.n}`, value: point.evidence_backed_pct }))} max={100} /><p className="di3-muted">Gaps resolved before the plan was built: {effect.evidence_at_commitment.value.map((point) => `${point.month} ${point.gaps_resolved_before_plan_pct == null ? '—' : `${point.gaps_resolved_before_plan_pct}%`}`).join(' · ')}</p></> : <EmptyChart type="line">{evidencePoints.length ? `So far: ${evidencePoints[0].evidence_backed_pct}% evidence-backed. The line starts with a second month.` : 'The evidence behind each month’s commitments will show here.'}</EmptyChart>}</article><article className="di3-card"><h4>Recurring gaps</h4><p className="di3-muted">Weaknesses that repeat across comparable decisions</p>{recurring.length ? <BarRows rows={recurring.map((item) => ({ label: item.label, value: item.decisions_affected }))} max={Math.max(...recurring.map((item) => item.decisions_affected), 1)} /> : <EmptyChart>Recurring normalized gaps will show here.</EmptyChart>}</article></div>
      <article className="di3-card"><h4>Outcomes and learning</h4><p className="di3-muted">A completed plan is implementation, never success</p>{effect.outcomes?.pursued ? <><BarRows rows={OUTCOME_STAGES.map(([key, label]) => ({ label, value: Number(effect.outcomes[key] || 0) }))} max={Math.max(Number(effect.outcomes.pursued || 0), 1)} />{effect.outcomes.latest_lesson && <p className="di3-muted">Latest lesson ({effect.outcomes.latest_lesson.option_name}): {effect.outcomes.latest_lesson.lesson}</p>}</> : <EmptyChart type="list">When you state what success looks like, intended results, measured outcomes and lessons will show here.</EmptyChart>}</article>
    </section>

    <section className="di3-section di3-register"><div className="di3-section-title"><div><p className="di3-kicker">Register</p><h3>Scored options, by decision</h3></div><span>{register.total} options</span></div>{rows.length ? <div className="di3-tablewrap"><table><thead><tr><th>Option</th>{data?.show_scope_control && scope === 'organization' && <th>Owner</th>}<th>State</th><th>Score</th><th>Evidence</th><th>Gaps</th><th>First scored</th><th>Time to plan</th></tr></thead><tbody>{rows.map((item, index) => <React.Fragment key={item.id}>{(item.show_group_heading ?? (index === 0 || rows[index - 1]?.record_id !== item.record_id)) && <tr className="di3-group"><td colSpan="8">{item.decision_title} · {item.decision_kind}</td></tr>}<tr className="di3-row" tabIndex="0" aria-expanded={expanded === item.id} onClick={() => setExpanded(expanded === item.id ? '' : item.id)} onKeyDown={(event) => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); setExpanded(expanded === item.id ? '' : item.id); } }}><td><b>{item.option_name}</b>{item.triggers?.length > 0 && <span className="di3-tag is-danger">Needs attention</span>}<OptionMarkers item={item} /></td>{data?.show_scope_control && scope === 'organization' && <td>{item.owner?.name}</td>}<td><span className={`di3-state-pill is-${item.state}`}>{STATES[item.state]}</span><small>{item.state_source?.replaceAll('_', ' ')}</small></td><td>{item.score ?? '—'}<small>{item.score_band}</small></td><td>{item.evidence_backed_pct == null ? '—' : `${item.evidence_backed_pct}%`}</td><td>{safe(item.gaps).length}</td><td>{formatDate(item.first_scored_at)}</td><td>{item.first_scored_at && item.first_plan_at ? formatDuration((new Date(item.first_plan_at) - new Date(item.first_scored_at)) / 3600000) : '—'}</td></tr>{expanded === item.id && <tr><td colSpan="8" className="di3-drill"><div><h4>Decision history</h4>{safe(item.history).length ? item.history.map((event, index) => <p key={index}><small>{formatDate(event.time)}</small> <b>{event.disposition?.replaceAll('_', ' ')}</b> · {event.source?.replaceAll('_', ' ')} {event.quote && <>“{event.quote}”</>}</p>) : <p>No disposition captured.</p>}</div>{(safe(item.conditions).length > 0 || item.against_recommendation) && <div><h4>Conditions and recommendation</h4>{safe(item.conditions).map((condition) => <p key={condition.signal_id}><b>{condition.content}</b> · {CONDITION_STATUS[condition.status] || condition.status}{condition.due_by ? ` · due ${formatDate(condition.due_by)}` : ''}</p>)}{item.against_recommendation && <p>Jaspen recommended {item.against_recommendation.jaspen_recommendation || 'otherwise'}; the decision to pursue is yours and is kept beside it.</p>}</div>}{safe(item.triggers).length > 0 && <div><h4>Needs attention</h4>{item.triggers.map((trigger, index) => <p key={index}><b>{TRIGGER_TITLES[trigger.kind] || trigger.kind}</b><br />{triggerLabel(trigger)}</p>)}</div>}<div><h4>Required checks</h4>{safe(item.required_checks).map((gate, index) => <span key={index} className="di3-check">{gate.label || gate.key}: {gate.status || 'not confirmed'}</span>)}</div><button type="button" onClick={() => navigate(`/new?session_id=${encodeURIComponent(item.thread_id)}`)}>Open project</button></td></tr>}</React.Fragment>)}</tbody></table></div> : <div className="di3-empty"><b>No scored options match these filters.</b><button type="button" onClick={clear}>Clear filters</button></div>}{register.pages > 1 && <div className="di3-pagination"><button type="button" disabled={page <= 1} onClick={() => setPage(page - 1)}>Previous</button><span>Page {page} of {register.pages}</span><button type="button" disabled={page >= register.pages} onClick={() => setPage(page + 1)}>Next</button></div>}</section>
  </section>;
}
