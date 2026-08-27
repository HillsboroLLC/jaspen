// filepath: src/Market/components/ThreadEditModal.jsx
import React from 'react';

export default function ThreadEditModal({
  open,
  onClose,

  // identifiers
  sessionId = null,
  threadId = null,

  // initial display values
  initialName = '',
  initialAdoptedAnalysisId = '',

  // auth fetch
  authFetch,

  // thread persistence mode
  threadMode = 'auto',

  // callbacks to refresh parent UI
  onSaved,
}) {
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);
  const [detailsWarning, setDetailsWarning] = React.useState(null);

  const [name, setName] = React.useState(initialName || '');
  const [adoptedAnalysisId, setAdoptedAnalysisId] = React.useState(initialAdoptedAnalysisId || '');
  const titleId = React.useId();
  const descriptionId = React.useId();
  const nameRef = React.useRef(initialName || '');
  const adoptedAnalysisIdRef = React.useRef(initialAdoptedAnalysisId || '');
  const initialAdoptedAnalysisIdRef = React.useRef(initialAdoptedAnalysisId || '');

  const [analysisOptions, setAnalysisOptions] = React.useState([]); // [{analysis_id,label,created_at}]

  // The thread revision observed when this modal hydrated. Sent back as
  // `base_revision` on rename so the server can refuse a write layered on a
  // version someone else has already replaced. A ref rather than state: it is
  // never rendered and must not re-run the hydrate effect.
  const baseRevisionRef = React.useRef(null);

  React.useEffect(() => {
    nameRef.current = name;
  }, [name]);

  React.useEffect(() => {
    adoptedAnalysisIdRef.current = adoptedAnalysisId;
  }, [adoptedAnalysisId]);

  // Reset form when modal opens or the target changes
  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setDetailsWarning(null);
    setName(initialName || '');
    setAdoptedAnalysisId(initialAdoptedAnalysisId || '');
    nameRef.current = initialName || '';
    adoptedAnalysisIdRef.current = initialAdoptedAnalysisId || '';
    initialAdoptedAnalysisIdRef.current = initialAdoptedAnalysisId || '';
    setAnalysisOptions([]);
  }, [open, initialName, initialAdoptedAnalysisId]);

  // Load analysis options when opened (from bundle)
  React.useEffect(() => {
    let alive = true;
    const targetThreadId = threadId || sessionId;
    if (!open || !targetThreadId || !authFetch) return;

    (async () => {
      const hydrateFromBundle = async () => {
        const res = await authFetch(`/api/v1/strategy/threads/${encodeURIComponent(targetThreadId)}/bundle`, {
          method: 'GET',
          headers: { Accept: 'application/json' },
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || data?.msg || `HTTP ${res.status}`);

        const snapshots = Array.isArray(data?.scorecard_snapshots) ? data.scorecard_snapshots : [];
        const opts = snapshots
          .map((snapshot) => {
            const id = snapshot?.id || '';
            const labelBase = snapshot?.label || snapshot?.project_name || nameRef.current || 'Analysis';
            const score = snapshot?.jaspen_score;
            const label = score !== null && score !== undefined ? `${labelBase} — ${score}` : labelBase;
            return id ? { analysis_id: id, label, created_at: snapshot?.createdAt || '' } : null;
          })
          .filter(Boolean);

        if (alive) {
          setAnalysisOptions(opts);
          if (data?.thread?.name && !nameRef.current) {
            setName(data.thread.name);
          }
          const selectedId = data?.selected_scorecard_id || '';
          if (selectedId && !adoptedAnalysisIdRef.current) {
            setAdoptedAnalysisId(selectedId);
          }
        }
      };

      const hydrateFromAiThread = async () => {
        const res = await authFetch(`/api/v1/ai-agent/threads/${encodeURIComponent(targetThreadId)}`, {
          method: 'GET',
          headers: { Accept: 'application/json' },
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || data?.msg || `HTTP ${res.status}`);

        const revision = data?.thread?.revision ?? data?.session?.revision;
        if (Number.isFinite(Number(revision))) baseRevisionRef.current = Number(revision);

        const hist = Array.isArray(data?.analysis_history) ? data.analysis_history : [];
        const opts = hist
          .map((h) => {
            const id = h?.analysis_id || h?.analysis_key || '';
            const created = h?.created_at || '';
            const score = h?.result?.jaspen_score ?? h?.jaspen_score ?? null;
            const labelBase =
              h?.result?.project_name ||
              h?.result?.compat?.title ||
              nameRef.current ||
              'Analysis';
            const label = score ? `${labelBase} — ${score}` : labelBase;
            return id ? { analysis_id: id, label, created_at: created } : null;
          })
          .filter(Boolean);

        if (alive) setAnalysisOptions(opts);

        const adopted = data?.adopted_analysis_id || '';
        if (alive && adopted && !adoptedAnalysisIdRef.current) setAdoptedAnalysisId(adopted);
      };

      try {
        setLoading(true);
        setDetailsWarning(null);
        if (threadMode === 'strategy') {
          await hydrateFromBundle();
        } else if (threadMode === 'ai-agent') {
          await hydrateFromAiThread();
        } else {
          try {
            await hydrateFromBundle();
          } catch {
            await hydrateFromAiThread();
          }
        }
      } catch (e) {
        if (alive) {
          setAnalysisOptions([]);
          setDetailsWarning('Analysis options are unavailable right now. You can still rename this initiative.');
        }
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, [open, sessionId, threadId, authFetch, threadMode]); // intentionally not depending on name

  const doSave = async () => {
    if (!authFetch) return;
    const targetThreadId = threadId || sessionId;
    if (!targetThreadId) return;
    setSaving(true);
    setError(null);

    try {
      // 1) Rename
      if (name && name.trim()) {
        // Declare the version this rename is layered on. The server requires
        // it for a shared organization project and answers 409 when the
        // project has moved on.
        const renameBody = JSON.stringify({
          name: name.trim(),
          ...(baseRevisionRef.current != null ? { base_revision: baseRevisionRef.current } : {}),
        });
        const renameEndpoints = threadMode === 'strategy'
          ? [`/api/v1/strategy/threads/${encodeURIComponent(targetThreadId)}`]
          : threadMode === 'ai-agent'
          ? [`/api/v1/ai-agent/threads/${encodeURIComponent(targetThreadId)}`]
          : [
              `/api/v1/ai-agent/threads/${encodeURIComponent(targetThreadId)}`,
              `/api/v1/strategy/threads/${encodeURIComponent(targetThreadId)}`,
            ];
        let renameSucceeded = false;
        let renameError = null;

        for (const endpoint of renameEndpoints) {
          const res = await authFetch(endpoint, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
            body: renameBody,
          });
          const data = await res.json().catch(() => ({}));
          if (res.ok) {
            renameSucceeded = true;
            break;
          }
          if (res.status === 409) {
            // A conflict is an answer, not a failed attempt. Stop here rather
            // than falling through to the sibling endpoint, and never retry:
            // the newer version is someone else's work.
            throw new Error(
              data?.error
              || 'This project changed since you opened it. Close and reopen it to get the latest version before renaming.'
            );
          }
          renameError = new Error(data?.error || data?.msg || `Rename failed (HTTP ${res.status})`);
        }

        if (!renameSucceeded && renameError) {
          throw renameError;
        }
      }

      // 2) Adopt analysis for AI context
      if (
        (threadMode === 'strategy' || threadMode === 'auto')
        && threadId
        && adoptedAnalysisId
        && adoptedAnalysisId !== (initialAdoptedAnalysisIdRef.current || '')
      ) {
        const r2 = await authFetch(`/api/v1/strategy/threads/${encodeURIComponent(threadId)}/adopt`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ analysis_id: adoptedAnalysisId }),
        });
        const d2 = await r2.json().catch(() => ({}));
        if (!r2.ok) throw new Error(d2?.error || d2?.msg || `Adopt failed (HTTP ${r2.status})`);
      }

      if (onSaved) onSaved({ name: name.trim(), adoptedAnalysisId });
      onClose?.();
    } catch (e) {
      setError(e?.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  };

  if (!open) return null;

  return (
    <div style={styles.backdrop} onMouseDown={onClose}>
      <div
        style={styles.modal}
        onMouseDown={(e) => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
      >
        <div style={styles.header}>
          <div>
            <div id={titleId} style={styles.title}>Edit Analysis</div>
            <div id={descriptionId} style={styles.sub}>
              {sessionId ? `Session: ${sessionId}` : ''}
            </div>
          </div>
          <button type="button" style={styles.close} onClick={onClose} aria-label="Close edit analysis dialog">✕</button>
        </div>

        {error && <div style={styles.error}>{error}</div>}

        <div style={styles.body}>
          <label style={styles.label}>Project name</label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Enter a project name"
            style={styles.input}
          />

          <div style={{ height: 14 }} />

          <label style={styles.label}>AI context (adopted analysis)</label>

          {loading ? (
            <div style={styles.muted}>Loading analyses…</div>
          ) : (
            <select
              value={adoptedAnalysisId || ''}
              onChange={(e) => setAdoptedAnalysisId(e.target.value)}
              style={styles.select}
              disabled={Boolean(detailsWarning)}
            >
              <option value="">(No adopted analysis)</option>
              {analysisOptions.map((o) => (
                <option key={o.analysis_id} value={o.analysis_id}>
                  {o.label}
                </option>
              ))}
            </select>
          )}

          {detailsWarning && <div style={styles.hint}>{detailsWarning}</div>}
          <div style={styles.hint}>
            Choosing an adopted analysis controls what the AI uses as the “current context” for this thread.
          </div>
        </div>

        <div style={styles.footer}>
          <button type="button" style={styles.btnSecondary} onClick={onClose} disabled={saving} aria-disabled={saving}>
            Cancel
          </button>
          <button type="button" style={styles.btnPrimary} onClick={doSave} disabled={saving || (!threadId && !sessionId)} aria-disabled={saving || (!threadId && !sessionId)}>
            {saving ? 'Saving…' : 'Save changes'}
          </button>
        </div>
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0,0,0,0.45)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    zIndex: 9999,
    padding: 18,
  },
  modal: {
    width: 'min(720px, 100%)',
    background: 'var(--color-surface-default)',
    borderRadius: 14,
    boxShadow: '0 10px 40px rgba(0,0,0,0.25)',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: 12,
    padding: '16px 18px',
    borderBottom: '1px solid rgba(0,0,0,0.08)',
  },
  title: { fontSize: 16, fontWeight: 800, color: 'var(--color-text-primary)' },
  sub: { fontSize: 12, color: 'var(--color-text-muted)', marginTop: 3 },
  close: {
    border: 'none',
    background: 'transparent',
    fontSize: 18,
    cursor: 'pointer',
    color: 'var(--color-text-secondary)',
  },
  body: { padding: 18 },
  label: { display: 'block', fontSize: 12, fontWeight: 700, color: 'var(--color-text-secondary)', marginBottom: 6 },
  input: {
    width: '100%',
    padding: '10px 12px',
    borderRadius: 10,
    border: '1px solid rgba(0,0,0,0.14)',
    outline: 'none',
    fontSize: 14,
  },
  select: {
    width: '100%',
    padding: '10px 12px',
    borderRadius: 10,
    border: '1px solid rgba(0,0,0,0.14)',
    background: 'var(--color-surface-default)',
    outline: 'none',
    fontSize: 14,
  },
  hint: { marginTop: 8, fontSize: 12, color: 'var(--color-text-muted)' },
  muted: { fontSize: 13, color: 'var(--color-text-muted)' },
  error: {
    margin: 18,
    padding: 12,
    borderRadius: 10,
    background: 'rgba(255,0,0,0.07)',
    border: '1px solid rgba(255,0,0,0.18)',
    color: 'var(--color-status-danger)',
    fontSize: 13,
  },
  footer: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 10,
    padding: 16,
    borderTop: '1px solid rgba(0,0,0,0.08)',
    background: 'var(--color-surface-subtle)',
  },
  btnSecondary: {
    padding: '10px 14px',
    borderRadius: 10,
    border: '1px solid rgba(22,31,59,0.18)',
    background: 'var(--color-surface-default)',
    cursor: 'pointer',
    fontWeight: 700,
    color: 'var(--color-text-primary)',
  },
  btnPrimary: {
    padding: '10px 14px',
    borderRadius: 10,
    border: 'none',
    background: 'var(--color-brand-navy)',
    cursor: 'pointer',
    fontWeight: 800,
    color: 'var(--color-text-inverse)',
  },
};
