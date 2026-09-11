// Records the ORGANIZATION'S decision for a completed analysis.
//
// Sits at the top of the trade-off view, above the analysis it was made from:
// "what did we decide" is the question a returning reader has first, and
// placing it above the scoring keeps it from reading as an output of that
// scoring. The recommendation and the decision are never the same act. Nothing
// here copies the recommendation into the decision on the user's behalf --
// Article 4, the human decides -- and no view-selection click (such as adopting
// a scorecard) is ever treated as an affirmation.
//
// Once a decision exists, the same panel closes the loop: what happened
// (outcome) and what we concluded (lesson). Those stay two separate acts --
// an observation is not a judgement, and it is the judgement that is reusable
// on future decisions. Both are append-only: a later entry never overwrites an
// earlier one, so the record shows how understanding developed.

import React from 'react';
import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';

const NAVY = '#161f3b';
const SLATE = '#5a6585';
const MUTED = '#8a93ad';
const ROSE = '#a0036c';
const LINE = '#d6e9ef';

// How the three derived backend states read to a person. "unknown" is a
// truthful engineering term and a confusing product one: the decision has not
// been made yet, so say that.
const STATE_LABEL = {
  current: 'Current decision',
  superseded: 'Superseded',
  unknown: 'Decision pending',
};

const OUTCOME_STATUS_OPTIONS = [
  ['achieved', 'Achieved'],
  ['partially_achieved', 'Partially achieved'],
  ['not_achieved', 'Not achieved'],
  ['too_early', 'Too early to tell'],
  ['abandoned', 'Abandoned'],
];

const STATE_TONE = {
  current: { fg: '#0e6b3f', bg: '#e3f5ea', bd: '#10b981' },
  superseded: { fg: '#5a6585', bg: '#eef0f5', bd: '#c9cfdf' },
  unknown: { fg: '#8a5406', bg: '#fdf2dc', bd: '#f59e0b' },
};

function StatePill({ state }) {
  const tone = STATE_TONE[state] || STATE_TONE.unknown;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '3px 9px', borderRadius: 3, whiteSpace: 'nowrap',
      fontFamily: 'JetBrains Mono, monospace', fontSize: 10,
      fontWeight: 500, letterSpacing: '0.08em', textTransform: 'uppercase',
      background: tone.bg, color: tone.fg, border: `1px solid ${tone.bd}`,
    }}>
      {STATE_LABEL[state] || STATE_LABEL.unknown}
    </span>
  );
}

async function api(path, options = {}) {
  const method = options.method || 'GET';
  const res = await fetch(`${API_BASE}/api/v1/decision-records${path}`, {
    credentials: 'include',
    ...options,
    headers: buildAuthHeaders({ 'Content-Type': 'application/json' }, method),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
  return data;
}

export default function RecordDecisionPanel({ threadId, alternatives = [], selectedAlternative = null }) {
  const [record, setRecord] = React.useState(null);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState(null);

  const [open, setOpen] = React.useState(false);
  const [confirming, setConfirming] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [choice, setChoice] = React.useState(selectedAlternative || '');
  const [statement, setStatement] = React.useState('');
  const [supersedesId, setSupersedesId] = React.useState('');
  const [candidates, setCandidates] = React.useState([]);
  const [justSaved, setJustSaved] = React.useState(null);

  // The learning loop. Separate forms, separate submissions: an outcome may be
  // recorded now and a lesson months later, when more is actually known.
  const [outcomeOpen, setOutcomeOpen] = React.useState(false);
  const [outcomeText, setOutcomeText] = React.useState('');
  const [outcomeStatus, setOutcomeStatus] = React.useState('');
  const [lessonOpen, setLessonOpen] = React.useState(false);
  const [lessonText, setLessonText] = React.useState('');

  const load = React.useCallback(async () => {
    if (!threadId) { setLoading(false); return; }
    setLoading(true);
    setError(null);
    try {
      const data = await api(`?thread_id=${encodeURIComponent(threadId)}&limit=1`);
      setRecord((data?.records || [])[0] || null);
    } catch (err) {
      setError(err?.message || 'Could not load the decision record.');
    } finally {
      setLoading(false);
    }
  }, [threadId]);

  React.useEffect(() => { void load(); }, [load]);

  // Only records this user may already see can be offered as a predecessor.
  // The search endpoint is permission-scoped, so an inaccessible record is
  // never a candidate — the selector cannot leak one by construction.
  const loadCandidates = React.useCallback(async () => {
    try {
      const data = await api('/search?current=all&limit=25');
      setCandidates(
        (data?.results || []).filter((r) => r.thread_id !== threadId)
      );
    } catch {
      setCandidates([]);
    }
  }, [threadId]);

  function beginRecording() {
    setChoice(selectedAlternative || '');
    setStatement('');
    setSupersedesId('');
    setConfirming(false);
    setOpen(true);
    void loadCandidates();
  }

  async function submit() {
    if (!record) return;
    setSaving(true);
    setError(null);
    try {
      // The decision statement is what the human typed. If they only picked an
      // alternative, the decision is that choice — still their words about
      // their choice, never the model's recommendation text.
      const decision = statement.trim() || (choice ? `Proceed with ${choice}.` : '');
      if (!decision) {
        setError('Enter the decision, or select the option you are choosing.');
        setSaving(false);
        return;
      }

      const updated = await api(`/${encodeURIComponent(record.id)}`, {
        method: 'PATCH',
        body: JSON.stringify({ final_decision: decision }),
      });

      let supersededTitle = null;
      if (supersedesId) {
        const prior = candidates.find((c) => c.id === supersedesId);
        supersededTitle = prior?.title || null;
        await api(`/${encodeURIComponent(record.id)}/supersedes`, {
          method: 'POST',
          body: JSON.stringify({ supersedes_id: supersedesId }),
        });
      }

      setRecord(updated?.record || null);
      setJustSaved({ supersededTitle });
      setOpen(false);
      setConfirming(false);
      await load();
    } catch (err) {
      setError(err?.message || 'Could not record the decision.');
    } finally {
      setSaving(false);
    }
  }

  async function submitOutcome() {
    if (!record || !outcomeText.trim()) {
      setError('Describe what happened.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api(`/${encodeURIComponent(record.id)}/outcomes`, {
        method: 'POST',
        body: JSON.stringify({
          summary: outcomeText.trim(),
          ...(outcomeStatus ? { status: outcomeStatus } : {}),
        }),
      });
      setRecord(updated?.record || null);
      setOutcomeOpen(false);
      setOutcomeText('');
      setOutcomeStatus('');
      await load();
    } catch (err) {
      setError(err?.message || 'Could not record the outcome.');
    } finally {
      setSaving(false);
    }
  }

  async function submitLesson() {
    if (!record || !lessonText.trim()) {
      setError('Write what the organization learned.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await api(`/${encodeURIComponent(record.id)}/lessons`, {
        method: 'POST',
        body: JSON.stringify({ lesson: lessonText.trim() }),
      });
      setRecord(updated?.record || null);
      setLessonOpen(false);
      setLessonText('');
      await load();
    } catch (err) {
      setError(err?.message || 'Could not record the lesson.');
    } finally {
      setSaving(false);
    }
  }

  if (loading || !threadId) return null;
  if (!record) return null;

  const state = record.current_state || 'unknown';
  const decided = Boolean(record.final_decision);
  const canEdit = record.can_edit !== false;
  const outcomes = Array.isArray(record.outcomes) ? record.outcomes : [];
  const lessons = Array.isArray(record.lessons_learned) ? record.lessons_learned : [];
  const hasOutcome = outcomes.length > 0;

  return (
    <div
      data-testid="record-decision-panel"
      style={{
        background: '#fff', border: `1px solid ${LINE}`, borderRadius: 12,
        padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 10,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <div style={{
          fontSize: 10.5, fontWeight: 600, letterSpacing: '0.08em',
          color: NAVY, textTransform: 'uppercase',
        }}>
          Decision
        </div>
        <StatePill state={state} />
      </div>

      {decided ? (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          <div style={{ fontSize: 13.5, color: NAVY, lineHeight: 1.5 }}>
            {record.final_decision}
          </div>
          <div style={{ fontSize: 11, color: MUTED }}>
            Recorded {record.decided_at ? new Date(record.decided_at).toLocaleDateString() : ''}
            {state === 'superseded' && ' · replaced by a later decision'}
          </div>
        </div>
      ) : (
        <div style={{ fontSize: 12.5, color: SLATE, lineHeight: 1.5 }}>
          {/* Never implies the recommendation is the organization's position. */}
          Jaspen has analysed this. No decision has been recorded yet.
        </div>
      )}

      {justSaved && (
        <div role="status" style={{ fontSize: 12, color: '#0e6b3f' }}>
          Decision recorded.
          {justSaved.supersededTitle
            ? ` “${justSaved.supersededTitle}” is now marked superseded.`
            : ''}
        </div>
      )}

      {error && (
        <div role="alert" style={{ fontSize: 12, color: ROSE }}>{error}</div>
      )}

      {canEdit && !open && (
        <div>
          <button
            type="button"
            onClick={beginRecording}
            style={{
              border: `1px solid ${NAVY}`, background: decided ? 'transparent' : NAVY,
              color: decided ? NAVY : '#fff', borderRadius: 6,
              padding: '7px 13px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
            }}
          >
            {decided ? 'Record a new decision' : 'Record decision'}
          </button>
          {decided && (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 6, lineHeight: 1.5 }}>
              {/* Changing the organization's mind creates new history rather
                  than rewriting what was decided before. */}
              Recording a new decision keeps this one as history.
            </div>
          )}
        </div>
      )}

      {open && (
        <div style={{
          border: `1px solid ${LINE}`, borderRadius: 8, padding: 14,
          display: 'flex', flexDirection: 'column', gap: 12, background: '#fff',
        }}>
          {alternatives.length > 0 && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <span style={{ fontSize: 11.5, fontWeight: 600, color: NAVY }}>
                Option you are choosing
              </span>
              <select
                value={choice}
                onChange={(e) => setChoice(e.target.value)}
                style={{ padding: '7px 9px', border: `1px solid ${LINE}`, borderRadius: 6, fontSize: 13 }}
              >
                <option value="">— none / described below —</option>
                {alternatives.map((name) => (
                  <option key={name} value={name}>{name}</option>
                ))}
              </select>
            </label>
          )}

          <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            <span style={{ fontSize: 11.5, fontWeight: 600, color: NAVY }}>
              The decision
            </span>
            <textarea
              value={statement}
              onChange={(e) => setStatement(e.target.value)}
              rows={3}
              placeholder="What is the organization deciding, and why?"
              style={{
                padding: '8px 10px', border: `1px solid ${LINE}`, borderRadius: 6,
                fontSize: 13, fontFamily: 'inherit', resize: 'vertical',
              }}
            />
          </label>

          {candidates.length > 0 && (
            <label style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              <span style={{ fontSize: 11.5, fontWeight: 600, color: NAVY }}>
                Does this replace an earlier decision? <span style={{ color: MUTED, fontWeight: 400 }}>(optional)</span>
              </span>
              <select
                value={supersedesId}
                onChange={(e) => setSupersedesId(e.target.value)}
                style={{ padding: '7px 9px', border: `1px solid ${LINE}`, borderRadius: 6, fontSize: 13 }}
              >
                <option value="">— no, this is a new decision —</option>
                {candidates.map((c) => (
                  <option key={c.id} value={c.id}>{c.title}</option>
                ))}
              </select>
            </label>
          )}

          {confirming ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 12.5, color: NAVY, lineHeight: 1.5 }}>
                This records your organization&rsquo;s decision and becomes part of its
                decision history.
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button" onClick={submit} disabled={saving}
                  style={{
                    border: 'none', background: NAVY, color: '#fff', borderRadius: 6,
                    padding: '7px 13px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {saving ? 'Recording…' : 'Confirm decision'}
                </button>
                <button
                  type="button" onClick={() => setConfirming(false)} disabled={saving}
                  style={{
                    border: `1px solid ${LINE}`, background: 'transparent', color: SLATE,
                    borderRadius: 6, padding: '7px 13px', fontSize: 12.5, cursor: 'pointer',
                  }}
                >
                  Back
                </button>
              </div>
            </div>
          ) : (
            <div style={{ display: 'flex', gap: 8 }}>
              <button
                type="button" onClick={() => setConfirming(true)}
                style={{
                  border: 'none', background: NAVY, color: '#fff', borderRadius: 6,
                  padding: '7px 13px', fontSize: 12.5, fontWeight: 600, cursor: 'pointer',
                }}
              >
                Review
              </button>
              <button
                type="button" onClick={() => { setOpen(false); setError(null); }}
                style={{
                  border: `1px solid ${LINE}`, background: 'transparent', color: SLATE,
                  borderRadius: 6, padding: '7px 13px', fontSize: 12.5, cursor: 'pointer',
                }}
              >
                Cancel
              </button>
            </div>
          )}
        </div>
      )}

      {/* The learning loop. Only offered once a decision exists: there is
          nothing to observe the result of until the organization decided
          something, and an undecided analysis must never acquire an
          "outcome" that implies one. */}
      {decided && (
        <div style={{
          borderTop: `1px solid ${LINE}`, paddingTop: 12,
          display: 'flex', flexDirection: 'column', gap: 10,
        }}>
          <div style={{
            fontSize: 10.5, fontWeight: 600, letterSpacing: '0.08em',
            color: NAVY, textTransform: 'uppercase',
          }}>
            What happened
          </div>

          {hasOutcome ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {outcomes.map((o) => (
                <div key={o.id || o.recorded_at} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <div style={{ fontSize: 13, color: NAVY, lineHeight: 1.5 }}>{o.summary}</div>
                  <div style={{ fontSize: 11, color: MUTED }}>
                    {(OUTCOME_STATUS_OPTIONS.find(([v]) => v === o.status) || [])[1] || 'Recorded'}
                    {o.recorded_by_name ? ` · ${o.recorded_by_name}` : ''}
                    {o.recorded_at ? ` · ${new Date(o.recorded_at).toLocaleDateString()}` : ''}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12.5, color: SLATE }}>No outcome recorded yet.</div>
          )}

          {canEdit && !outcomeOpen && (
            <div>
              <button
                type="button" onClick={() => { setOutcomeOpen(true); setError(null); }}
                style={{
                  border: `1px solid ${NAVY}`, background: 'transparent', color: NAVY,
                  borderRadius: 6, padding: '6px 11px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                }}
              >
                {hasOutcome ? 'Add another observation' : 'Record outcome'}
              </button>
            </div>
          )}

          {outcomeOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <textarea
                value={outcomeText}
                onChange={(e) => setOutcomeText(e.target.value)}
                rows={2}
                placeholder="What actually happened?"
                style={{
                  padding: '8px 10px', border: `1px solid ${LINE}`, borderRadius: 6,
                  fontSize: 13, fontFamily: 'inherit', resize: 'vertical',
                }}
              />
              <select
                value={outcomeStatus}
                aria-label="Outcome status"
                onChange={(e) => setOutcomeStatus(e.target.value)}
                style={{ padding: '6px 9px', border: `1px solid ${LINE}`, borderRadius: 6, fontSize: 12.5 }}
              >
                <option value="">— did it meet the objective? (optional) —</option>
                {OUTCOME_STATUS_OPTIONS.map(([value, label]) => (
                  <option key={value} value={value}>{label}</option>
                ))}
              </select>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button" onClick={submitOutcome} disabled={saving}
                  style={{
                    border: 'none', background: NAVY, color: '#fff', borderRadius: 6,
                    padding: '6px 11px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {saving ? 'Saving…' : 'Save outcome'}
                </button>
                <button
                  type="button" onClick={() => { setOutcomeOpen(false); setError(null); }}
                  style={{
                    border: `1px solid ${LINE}`, background: 'transparent', color: SLATE,
                    borderRadius: 6, padding: '6px 11px', fontSize: 12, cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}

          <div style={{
            fontSize: 10.5, fontWeight: 600, letterSpacing: '0.08em',
            color: NAVY, textTransform: 'uppercase', marginTop: 4,
          }}>
            What we learned
          </div>

          {lessons.length > 0 ? (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {lessons.map((l) => (
                <div key={l.id || l.recorded_at} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  <div style={{ fontSize: 13, color: NAVY, lineHeight: 1.5 }}>{l.lesson}</div>
                  <div style={{ fontSize: 11, color: MUTED }}>
                    {l.recorded_by_name || 'Recorded'}
                    {l.recorded_at ? ` · ${new Date(l.recorded_at).toLocaleDateString()}` : ''}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div style={{ fontSize: 12.5, color: SLATE }}>No lessons recorded yet.</div>
          )}

          {canEdit && !lessonOpen && (
            <div>
              <button
                type="button" onClick={() => { setLessonOpen(true); setError(null); }}
                style={{
                  border: `1px solid ${NAVY}`, background: 'transparent', color: NAVY,
                  borderRadius: 6, padding: '6px 11px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                }}
              >
                Add lesson
              </button>
              {!hasOutcome && (
                <span style={{ fontSize: 11, color: MUTED, marginLeft: 8 }}>
                  You can add this later, once you know more.
                </span>
              )}
            </div>
          )}

          {lessonOpen && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <textarea
                value={lessonText}
                onChange={(e) => setLessonText(e.target.value)}
                rows={2}
                placeholder="What should we do differently next time?"
                style={{
                  padding: '8px 10px', border: `1px solid ${LINE}`, borderRadius: 6,
                  fontSize: 13, fontFamily: 'inherit', resize: 'vertical',
                }}
              />
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  type="button" onClick={submitLesson} disabled={saving}
                  style={{
                    border: 'none', background: NAVY, color: '#fff', borderRadius: 6,
                    padding: '6px 11px', fontSize: 12, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  {saving ? 'Saving…' : 'Save lesson'}
                </button>
                <button
                  type="button" onClick={() => { setLessonOpen(false); setError(null); }}
                  style={{
                    border: `1px solid ${LINE}`, background: 'transparent', color: SLATE,
                    borderRadius: 6, padding: '6px 11px', fontSize: 12, cursor: 'pointer',
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
