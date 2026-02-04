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

  // callbacks to refresh parent UI
  onSaved,
}) {
  const [loading, setLoading] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState(null);

  const [name, setName] = React.useState(initialName || '');
  const [adoptedAnalysisId, setAdoptedAnalysisId] = React.useState(initialAdoptedAnalysisId || '');

  const [analysisOptions, setAnalysisOptions] = React.useState([]); // [{analysis_id,label,created_at}]

  // Reset form when modal opens or the target changes
  React.useEffect(() => {
    if (!open) return;
    setError(null);
    setName(initialName || '');
    setAdoptedAnalysisId(initialAdoptedAnalysisId || '');
    setAnalysisOptions([]);
  }, [open, initialName, initialAdoptedAnalysisId]);

  // Load analysis options when opened (from bundle)
  React.useEffect(() => {
    let alive = true;
    if (!open || !sessionId || !authFetch) return;

    (async () => {
      try {
        setLoading(true);
        setError(null);

        const res = await authFetch(`/api/ai-agent/threads/${encodeURIComponent(sessionId)}`, {
          method: 'GET',
          headers: { Accept: 'application/json' },
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data?.error || data?.msg || `HTTP ${res.status}`);

        // Expected shapes we can tolerate:
        // data.analysis_history = [{analysis_id, created_at, result:{project_name, score_category, market_iq_score}}]
        const hist = Array.isArray(data?.analysis_history) ? data.analysis_history : [];
        const opts = hist
          .map((h) => {
            const id = h?.analysis_id || h?.analysis_key || '';
            const created = h?.created_at || '';
            const score = h?.result?.market_iq_score ?? h?.market_iq_score ?? null;
            const labelBase =
              h?.result?.project_name ||
              h?.result?.compat?.title ||
              name ||
              'Analysis';
            const label = score ? `${labelBase} — ${score}` : labelBase;
            return id ? { analysis_id: id, label, created_at: created } : null;
          })
          .filter(Boolean);

        if (alive) setAnalysisOptions(opts);

        // If backend provides adopted/current id in bundle, prefer it
        const adopted = data?.adopted_analysis_id || '';
        if (alive && adopted && !adoptedAnalysisId) setAdoptedAnalysisId(adopted);
      } catch (e) {
        if (alive) setError(e?.message || 'Failed to load thread details');
      } finally {
        if (alive) setLoading(false);
      }
    })();

    return () => {
      alive = false;
    };
  }, [open, sessionId, authFetch]); // intentionally not depending on name

  const doSave = async () => {
    if (!authFetch) return;
    if (!sessionId) return;
    setSaving(true);
    setError(null);

    try {
      // 1) Rename
      // You may already have an endpoint. If not, you'll add it backend-side.
      // This expects: PATCH /api/ai-agent/threads/:sid { name }
      if (name && name.trim()) {
        const r1 = await authFetch(`/api/ai-agent/threads/${encodeURIComponent(sessionId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
          body: JSON.stringify({ name: name.trim() }),
        });
        const d1 = await r1.json().catch(() => ({}));
        if (!r1.ok) throw new Error(d1?.error || d1?.msg || `Rename failed (HTTP ${r1.status})`);
      }

      // 2) Adopt analysis for AI context
      // You likely already have thread_id. If not, backend can derive from session.
      // Expected: POST /api/market-iq/threads/:threadId/adopt { analysis_id }
      if (threadId && adoptedAnalysisId) {
        const r2 = await authFetch(`/api/market-iq/threads/${encodeURIComponent(threadId)}/adopt`, {
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
      <div style={styles.modal} onMouseDown={(e) => e.stopPropagation()}>
        <div style={styles.header}>
          <div>
            <div style={styles.title}>Edit Analysis</div>
            <div style={styles.sub}>
              {sessionId ? `Session: ${sessionId}` : ''}
            </div>
          </div>
          <button style={styles.close} onClick={onClose}>✕</button>
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
            >
              <option value="">(No adopted analysis)</option>
              {analysisOptions.map((o) => (
                <option key={o.analysis_id} value={o.analysis_id}>
                  {o.label}
                </option>
              ))}
            </select>
          )}

          <div style={styles.hint}>
            Choosing an adopted analysis controls what the AI uses as the “current context” for this thread.
          </div>
        </div>

        <div style={styles.footer}>
          <button style={styles.btnSecondary} onClick={onClose} disabled={saving}>
            Cancel
          </button>
          <button style={styles.btnPrimary} onClick={doSave} disabled={saving || (!threadId && !sessionId)}>
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
    background: '#fff',
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
  title: { fontSize: 16, fontWeight: 800, color: '#161f3b' },
  sub: { fontSize: 12, color: '#64748b', marginTop: 3 },
  close: {
    border: 'none',
    background: 'transparent',
    fontSize: 18,
    cursor: 'pointer',
    color: '#334155',
  },
  body: { padding: 18 },
  label: { display: 'block', fontSize: 12, fontWeight: 700, color: '#334155', marginBottom: 6 },
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
    background: '#fff',
    outline: 'none',
    fontSize: 14,
  },
  hint: { marginTop: 8, fontSize: 12, color: '#64748b' },
  muted: { fontSize: 13, color: '#64748b' },
  error: {
    margin: 18,
    padding: 12,
    borderRadius: 10,
    background: 'rgba(255,0,0,0.07)',
    border: '1px solid rgba(255,0,0,0.18)',
    color: '#7f1d1d',
    fontSize: 13,
  },
  footer: {
    display: 'flex',
    justifyContent: 'flex-end',
    gap: 10,
    padding: 16,
    borderTop: '1px solid rgba(0,0,0,0.08)',
    background: '#f8fafc',
  },
  btnSecondary: {
    padding: '10px 14px',
    borderRadius: 10,
    border: '1px solid rgba(22,31,59,0.18)',
    background: '#fff',
    cursor: 'pointer',
    fontWeight: 700,
    color: '#161f3b',
  },
  btnPrimary: {
    padding: '10px 14px',
    borderRadius: 10,
    border: 'none',
    background: '#161f3b',
    cursor: 'pointer',
    fontWeight: 800,
    color: '#fff',
  },
};
