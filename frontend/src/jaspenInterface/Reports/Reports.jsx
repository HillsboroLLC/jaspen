import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faFilePdf, faTrashCan, faWandMagicSparkles } from '@fortawesome/free-solid-svg-icons';
import { API_BASE } from '../../config/apiBase';
import { authFetch, buildAuthHeaders } from '../../shared/auth/http';
import ConfirmDialog from '../../shared/components/ConfirmDialog';
import SkeletonBlock from '../../shared/components/SkeletonLoader';
import EmptyState from '../../homeSections/homeUi/EmptyState';
import './Reports.css';
import AppMenu from '../shared/AppMenu';
import JaspenAiDrawer from '../Workspace/JaspenAiDrawer';

const REPORT_TYPES = [
  { value: 'executive_summary', label: 'Executive Summary' },
  { value: 'detailed', label: 'Detailed Analysis' },
  { value: 'portfolio', label: 'Portfolio Overview' },
];

function authHeaders(method = 'GET') {
  return buildAuthHeaders({ 'Content-Type': 'application/json' }, method);
}

function parseScore(session) {
  const result = session?.result && typeof session.result === 'object' ? session.result : {};
  const candidates = [
    result?.jaspen_score,
    result?.overall_score,
    result?.score,
    session?.jaspen_score,
  ];
  for (const value of candidates) {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

export default function Reports() {
  const [threads, setThreads] = useState([]);
  const [selectedThreadId, setSelectedThreadId] = useState('');
  const [reportType, setReportType] = useState('executive_summary');
  const [reports, setReports] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [message, setMessage] = useState('');
  const [confirmDialog, setConfirmDialog] = useState(null);
  const [jaspenOpen, setJaspenOpen] = useState(false);
  const [assistantInput, setAssistantInput] = useState('');
  const [assistantMessages, setAssistantMessages] = useState([
    {
      role: 'assistant',
      text: 'I can help choose the right report format based on your audience.',
    },
  ]);

  const loadThreads = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/ai-agent/threads`, {
      credentials: 'include',
      headers: authHeaders('GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.success) {
      throw new Error(data?.error || `Unable to load analyses (${res.status})`);
    }

    const rows = (Array.isArray(data.sessions) ? data.sessions : [])
      .map((session) => {
        const threadId = String(session?.session_id || '').trim();
        if (!threadId) return null;
        const score = parseScore(session);
        const status = String(session?.status || '').toLowerCase();
        const completed = status === 'completed' || Number.isFinite(score);
        return {
          threadId,
          completed,
          name: String(session?.name || session?.result?.project_name || `Thread ${threadId}`).trim(),
          score,
        };
      })
      .filter((item) => item && item.completed);

    setThreads(rows);
    if (!selectedThreadId && rows.length) {
      setSelectedThreadId(rows[0].threadId);
    }
  }, [selectedThreadId]);

  const loadReports = useCallback(async () => {
    const res = await authFetch(`${API_BASE}/api/v1/reports`, {
      credentials: 'include',
      headers: authHeaders('GET'),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data?.error || `Unable to load reports (${res.status})`);
    }
    setReports(Array.isArray(data?.reports) ? data.reports : []);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      await Promise.all([loadThreads(), loadReports()]);
    } catch (err) {
      setError(err?.message || 'Failed to load report data.');
    } finally {
      setLoading(false);
    }
  }, [loadThreads, loadReports]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  useEffect(() => {
    const observer = new MutationObserver(() => {
      if (document.body.classList.contains('jaspen-sidebar-open')) {
        setJaspenOpen(false);
      }
    });
    observer.observe(document.body, { attributes: true, attributeFilter: ['class'] });
    return () => observer.disconnect();
  }, []);

  const openJaspen = useCallback(() => {
    document.body.classList.remove('jaspen-sidebar-open');
    setJaspenOpen(true);
  }, []);

  const sendAssistant = useCallback(() => {
    const text = String(assistantInput || '').trim();
    if (!text) return;
    setAssistantMessages((prev) => [
      ...prev,
      { role: 'user', text },
      {
        role: 'assistant',
        text: 'Use Executive Summary for leadership and Detailed Analysis for operator reviews.',
      },
    ]);
    setAssistantInput('');
  }, [assistantInput]);

  const selectedThread = useMemo(
    () => threads.find((item) => item.threadId === selectedThreadId) || null,
    [threads, selectedThreadId]
  );

  async function generateReport() {
    if (!selectedThreadId) return;
    setBusy(true);
    setError('');
    setMessage('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/reports/generate`, {
        method: 'POST',
        credentials: 'include',
        headers: authHeaders('POST'),
        body: JSON.stringify({ thread_id: selectedThreadId, report_type: reportType }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data?.error || `Report generation failed (${res.status})`);
      }
      setMessage(`Report generated: ${data?.filename || 'download ready'}`);
      await loadReports();
    } catch (err) {
      setError(err?.message || 'Failed to generate report.');
    } finally {
      setBusy(false);
    }
  }

  async function deleteReport(reportId) {
    if (!reportId) return;
    setConfirmDialog({
      title: 'Delete report',
      message: 'Delete this report? This cannot be undone.',
      confirmLabel: 'Delete report',
      confirmVariant: 'danger',
      onConfirm: async () => {
        setConfirmDialog(null);
        setBusy(true);
        setError('');
        setMessage('');
        try {
          const res = await authFetch(`${API_BASE}/api/v1/reports/${encodeURIComponent(reportId)}`, {
            method: 'DELETE',
            credentials: 'include',
            headers: authHeaders('DELETE'),
          });
          const data = await res.json().catch(() => ({}));
          if (!res.ok) {
            throw new Error(data?.error || `Delete failed (${res.status})`);
          }
          await loadReports();
        } catch (err) {
          setError(err?.message || 'Failed to delete report.');
        } finally {
          setBusy(false);
        }
      },
    });
  }

  return (
    <div className={`reports-page int-page${jaspenOpen ? ' drawer-open' : ''}`}>
      <AppMenu />
      <div className="reports-inner int-page-inner">
      <header className="reports-header int-page-head">
        <div>
          <p className="int-eyebrow">Reports</p>
          <h1>Reports</h1>
          <p>Generate executive and detailed PDFs from completed analyses.</p>
        </div>
      </header>

      <section className="reports-section">
        <h2>Generate Report</h2>
        <div className="reports-generate-form">
          <select value={selectedThreadId} onChange={(event) => setSelectedThreadId(event.target.value)}>
            {!threads.length && <option value="">No completed analyses available</option>}
            {threads.map((thread) => (
              <option key={thread.threadId} value={thread.threadId}>
                {thread.name}{Number.isFinite(thread.score) ? ` · Score ${Math.round(thread.score)}` : ''}
              </option>
            ))}
          </select>
          <select value={reportType} onChange={(event) => setReportType(event.target.value)}>
            {REPORT_TYPES.map((item) => (
              <option key={item.value} value={item.value}>{item.label}</option>
            ))}
          </select>
          <button type="button" onClick={generateReport} disabled={busy || !selectedThreadId} aria-disabled={busy || !selectedThreadId}>
            <FontAwesomeIcon icon={faWandMagicSparkles} /> {busy ? 'Generating...' : 'Generate'}
          </button>
        </div>
        {selectedThread && (
          <p className="reports-generate-context">
            Source project: <strong>{selectedThread.name}</strong>
          </p>
        )}
      </section>

      {loading && (
        <div className="reports-loading" role="status" aria-live="polite" aria-label="Loading reports">
          <SkeletonBlock width="22%" height={14} />
          <div className="reports-loading-row">
            <SkeletonBlock height={42} />
            <SkeletonBlock height={42} />
            <SkeletonBlock height={42} />
          </div>
          <div className="reports-loading-table">
            {Array.from({ length: 4 }).map((_, idx) => (
              <SkeletonBlock key={`reports-skeleton-row-${idx}`} height={18} />
            ))}
          </div>
        </div>
      )}
      {!loading && error && (
        <div className="reports-state reports-state-error" role="status" aria-live="polite">
          <p>{error}</p>
          <button type="button" className="int-btn int-btn-ghost reports-retry-btn" onClick={refresh}>
            Retry
          </button>
        </div>
      )}
      {!loading && !error && message && <div className="reports-state reports-state-success" role="status" aria-live="polite">{message}</div>}

      {!loading && !error && (
        <section className="reports-section">
          <h2>Generated Reports</h2>
          {reports.length === 0 ? (
            <EmptyState
              className="reports-state"
              title="No reports generated yet"
              description="Create your first export to share summary insights with your team."
              icon={<FontAwesomeIcon icon={faFilePdf} />}
              action={(
                <button
                  type="button"
                  className="int-btn int-btn-primary"
                  onClick={generateReport}
                  disabled={busy || !selectedThreadId}
                  aria-disabled={busy || !selectedThreadId}
                >
                  <FontAwesomeIcon icon={faWandMagicSparkles} />
                  {busy ? 'Generating...' : 'Generate report'}
                </button>
              )}
            />
          ) : (
            <div className="reports-table-wrap">
              <table className="reports-table">
                <thead>
                  <tr>
                    <th>Report Name</th>
                    <th>Type</th>
                    <th>Project</th>
                    <th>Generated Date</th>
                    <th>Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {reports.map((report) => (
                    <tr key={report.report_id}>
                      <td>{report.filename}</td>
                      <td>{report.report_type_label || report.report_type}</td>
                      <td>{report.project_name || 'Untitled'}</td>
                      <td>{report.created_at ? new Date(report.created_at).toLocaleString() : 'N/A'}</td>
                      <td>
                        <a
                          className="reports-action"
                          href={`${API_BASE}${report.download_url || `/api/v1/reports/${report.report_id}/download`}`}
                          target="_blank"
                          rel="noreferrer"
                        >
                          <FontAwesomeIcon icon={faFilePdf} /> Download PDF
                        </a>
                        <button
                          type="button"
                          className="reports-action reports-action-danger"
                          onClick={() => deleteReport(report.report_id)}
                          disabled={busy} aria-disabled={busy}
                        >
                          <FontAwesomeIcon icon={faTrashCan} /> Delete
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      </div>
      <ConfirmDialog
        isOpen={Boolean(confirmDialog)}
        title={confirmDialog?.title}
        message={confirmDialog?.message}
        confirmLabel={confirmDialog?.confirmLabel}
        confirmVariant={confirmDialog?.confirmVariant}
        pending={busy}
        onCancel={() => setConfirmDialog(null)}
        onConfirm={() => confirmDialog?.onConfirm?.()}
      />
      <JaspenAiDrawer
        isOpen={jaspenOpen}
        onOpen={openJaspen}
        onClose={() => setJaspenOpen(false)}
        messages={assistantMessages}
        input={assistantInput}
        onInputChange={setAssistantInput}
        onSend={sendAssistant}
        busy={false}
        starterPrompts={[
          'Which report format should I use for leadership?',
          'What should I include in the narrative summary?',
        ]}
        placeholder="Ask Jaspen about reports..."
      />
    </div>
  );
}
