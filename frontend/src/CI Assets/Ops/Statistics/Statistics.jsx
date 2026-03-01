// File: frontend/src/Ops/Statistics/Statistics.jsx
import React, { useState, useRef, useEffect } from 'react';
import styles from './Statistics.module.css';
import { useAuth } from '../../All/shared/auth/AuthContext';
import { useNavigate } from 'react-router-dom';
import { useAdminSettings } from '../context/AdminContext';
import ReportsModal from './ReportsModal';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import './Statistics_Reports.css';

// Allow pointing frontend to a DO-hosted backend via env
const API_BASE =
  (typeof import.meta !== 'undefined' && import.meta.env && import.meta.env.VITE_API_BASE) ||
  (typeof process !== 'undefined' && process.env && process.env.REACT_APP_API_BASE) ||
  'https://api.sekki.io';

const ALL_TABS = [
  'Descriptive Stats',
  'Correlations',
  'Regression',
  'ANOVA',
  'T-Test',
  'Chi-Square'
];

/* ---------------- Persistent History (backend + local fallback) --------------- */
const HISTORY_STORAGE_KEY = 'sekki_stats_history';

function loadLocalHistory() {
  try {
    const raw = localStorage.getItem(HISTORY_STORAGE_KEY);
    const list = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list : [];
  } catch {
    return [];
  }
}

function saveLocalHistory(list) {
  try {
    localStorage.setItem(HISTORY_STORAGE_KEY, JSON.stringify(list || []));
  } catch {}
}

async function fetchStatsHistory() {
  // Try backend first
  try {
    const res = await fetch(`${API_BASE}/api/statistical-analysis/history`, {
      method: 'GET',
      credentials: 'include'
    });
    if (res.ok) {
      const data = await res.json().catch(() => null);
      const list = (data && (data.items || data.history)) || [];
      if (Array.isArray(list)) {
        const norm = list.map((x) => ({
          client_id: x.client_id || x.id || x.token || `${Date.now()}_${Math.random().toString(36).slice(2)}`,
          title: x.title || x.filename || 'Analysis',
          date: x.date || x.created_at || new Date().toLocaleString(),
          testsCount: Number.isFinite(x.testsCount) ? x.testsCount : (Array.isArray(x.tests) ? x.tests.length : (x.testsCount || 0)),
          snapshot: x.snapshot || null // prefer backend snapshot if present
        }));
        // Merge with local, preferring backend (by client_id)
        const local = loadLocalHistory();
        const merged = [
          ...norm,
          ...local.filter(l => !norm.some(n => n.client_id === l.client_id))
        ];
        saveLocalHistory(merged);
        return merged;
      }
    }
  } catch {}
  // Fallback to local
  return loadLocalHistory();
}

async function fetchStatsHistoryItem(clientId) {
  try {
    const res = await fetch(`${API_BASE}/api/statistical-analysis/history/${encodeURIComponent(clientId)}`, {
      method: 'GET',
      credentials: 'include'
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data || null;
  } catch {
    return null;
  }
}

async function saveStatsHistoryItem(item) {
  // Update local immediately (optimistic UI)
  const list = loadLocalHistory();
  const idx = list.findIndex((h) => h.client_id === item.client_id);
  const display = {
    client_id: item.client_id,
    title: item.title,
    date: item.date || new Date().toLocaleString(),
    testsCount: item.testsCount || 0,
    snapshot: item.snapshot || null
  };
  const next = idx >= 0 ? [...list.slice(0, idx), display, ...list.slice(idx + 1)] : [display, ...list];
  saveLocalHistory(next);

  // Fire-and-forget backend save
  try {
    await fetch(`${API_BASE}/api/statistical-analysis/history`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(item) // include full item (with snapshot)
    });
  } catch {}
  return true;
}

async function deleteStatsHistoryItem(clientId) {
  // Update local immediately
  const list = loadLocalHistory().filter((h) => h.client_id !== clientId);
  saveLocalHistory(list);

  // Try backend delete (ignore failures)
  try {
    await fetch(`${API_BASE}/api/statistical-analysis/history/${encodeURIComponent(clientId)}`, {
      method: 'DELETE',
      credentials: 'include'
    });
  } catch {}
  return true;
}
/* ---------------------------------------------------------------------------- */

const Statistics = () => {
  const { adminSettings } = useAdminSettings();
  useAuth();
  const navigate = useNavigate();

  // UI state
  const [historySidebarOpen, setHistorySidebarOpen] = useState(false);
  const [activeResultTab, setActiveResultTab] = useState(null);
  const [resultsPanelOpen, setResultsPanelOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  // Chat state
  const [messages, setMessages] = useState([]);
  const [inputValue, setInputValue] = useState('');

  // Data/analysis state
  const [uploadedFile, setUploadedFile] = useState(null);
  const [lastFile, setLastFile] = useState(null);
  const [lastTarget, setLastTarget] = useState('');
  const [lastGroup, setLastGroup] = useState('');
  const [analysisResults, setAnalysisResults] = useState({});
  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [datasetInfo, setDatasetInfo] = useState(null);
  const [numericCols, setNumericCols] = useState([]);
  const [categoricalCols, setCategoricalCols] = useState([]);
  const [showPicker, setShowPicker] = useState(false);
  const [pickerTarget, setPickerTarget] = useState('');
  const [pickerGroup, setPickerGroup] = useState('');

  // Reports modal
  const [showReportsModal, setShowReportsModal] = useState(false);

  // Load persisted history at mount
  useEffect(() => {
    (async () => {
      try {
        const server = await fetchStatsHistory();
        if (server.length) setAnalysisHistory(server);
      } catch (e) {
        console.debug('stats history fetch skipped', e);
        setAnalysisHistory(loadLocalHistory());
      }
    })();
  }, []);

  // Toast/snackbar
  const [toast, setToast] = useState({ open: false, kind: 'info', text: '' });
  const showToast = (text, kind = 'info', ttl = 3500) => {
    setToast({ open: true, kind, text });
    window.clearTimeout(showToast._t);
    showToast._t = window.setTimeout(() => setToast(t => ({ ...t, open: false })), ttl);
  };

  // Share dropdown state
  const [shareOpen, setShareOpen] = useState(false);
  const [shareIncludeInsights, setShareIncludeInsights] = useState(true);
  const shareWrapperRef = useRef(null);

  // Refs
  const fileInputRef = useRef(null);
  const chatMessagesRef = useRef(null);
  const rawResultsRef = useRef(null); // full /comprehensive results for export/report

  // Close Share dropdown on outside click + ESC
  useEffect(() => {
    const onDocClick = (e) => {
      if (!shareOpen) return;
      if (shareWrapperRef.current && !shareWrapperRef.current.contains(e.target)) {
        setShareOpen(false);
      }
    };
    const onEsc = (e) => { if (e.key === 'Escape') setShareOpen(false); };
    document.addEventListener('mousedown', onDocClick);
    document.addEventListener('keydown', onEsc);
    return () => {
      document.removeEventListener('mousedown', onDocClick);
      document.removeEventListener('keydown', onEsc);
    };
  }, [shareOpen]);

  const tabHasData = (tabName) => Boolean(analysisResults?.[tabName]);

  const fmtNum = (v) =>
    typeof v === 'number' && isFinite(v)
      ? Number(v).toLocaleString(undefined, { maximumFractionDigits: 6 })
      : v === null || v === undefined
      ? ''
      : String(v);

  const toCsv = (rows) => {
    if (!rows?.length) return '';
    const headers = Object.keys(rows[0]);
    const esc = (s) => {
      const t = String(s ?? '');
      return /[",\n]/.test(t) ? `"${t.replace(/"/g, '""')}"` : t;
    };
    return [headers.map(esc).join(','), ...rows.map(r => headers.map(h => esc(r[h])).join(','))].join('\n');
  };

  const makeCsvForTab = (tabName, data) => {
    if (!data) return '';
    if (tabName === 'Descriptive Stats') {
      const cols = Object.keys(data);
      const metrics = Array.from(new Set(cols.flatMap((c) => Object.keys(data[c] || {}))));
      const rows = metrics.map((m) => {
        const row = { metric: m };
        cols.forEach((c) => (row[c] = data[c]?.[m]));
        return row;
      });
      return toCsv(rows);
    }
    if (tabName === 'Correlations') {
      const vars = Object.keys(data);
      const rows = vars.map((r) => {
        const row = { variable: r };
        vars.forEach((c) => (row[c] = data[r]?.[c]));
        return row;
      });
      return toCsv(rows);
    }
    if (tabName === 'ANOVA') {
      const rows = [
        { stat: 'target', value: data.target },
        { stat: 'group', value: data.group },
        { stat: 'k_groups', value: data.k_groups },
        { stat: 'f_stat', value: data.f_stat },
        { stat: 'p_value', value: data.p_value },
        { stat: 'eta_squared', value: data.eta_squared },
      ];
      const groupRows = Object.keys(data.group_means || {}).map((g) => ({
        group: g,
        mean: data.group_means[g],
        count: data.group_counts?.[g],
      }));
      return [toCsv(rows), '', toCsv([{ section: 'Group Summary' }]), toCsv(groupRows)].filter(Boolean).join('\n');
    }
    if (tabName === 'T-Test') {
      const rows = [
        { stat: 'target', value: data.target },
        { stat: 'group', value: data.group },
        { stat: 'groups', value: (data.groups || []).join(' vs ') },
        { stat: 'equal_var_assumed', value: data.equal_var_assumed },
        { stat: 'levene_stat', value: data.levene_stat },
        { stat: 'levene_p', value: data.levene_p },
        { stat: 't_stat', value: data.t_stat },
        { stat: 'p_value', value: data.p_value },
        { stat: 'cohens_d', value: data.cohens_d },
      ];
      const gms = data.group_means || {};
      const gcs = data.group_counts || {};
      const groupRows = Object.keys(gms).map((g) => ({
        group: g,
        mean: gms[g],
        count: gcs[g],
      }));
      return [toCsv(rows), '', toCsv([{ section: 'Group Summary' }]), toCsv(groupRows)].filter(Boolean).join('\n');
    }
    try {
      const flat = Object.entries(data).map(([k, v]) => ({ key: k, value: typeof v === 'object' ? JSON.stringify(v) : v }));
      return toCsv(flat);
    } catch {
      return '';
    }
  };

  // ------------ Backend-powered downloads (honor Content-Disposition) ------------
  const pickFilenameFromHeaders = (res, fallback) => {
    const disp = res.headers.get('Content-Disposition') || '';
    const m = disp.match(/filename\*=UTF-8''([^;]+)|filename="?([^"]+)"?/i);
    const name = decodeURIComponent(m?.[1] || m?.[2] || '').trim();
    return name || fallback;
  };

  // Build the results payload for downloads, optionally stripping AI insights.
  const buildResultsForDownload = (includeInsights) => {
    const base = rawResultsRef.current || {};
    if (includeInsights) return base;
    const copy = JSON.parse(JSON.stringify(base || {}));
    if (copy.ai_insights) delete copy.ai_insights;
    if (copy.results && copy.results.ai_insights) delete copy.results.ai_insights;
    return copy;
  };

  async function downloadExportZip(results) {
    const res = await fetch(`${API_BASE}/api/statistical-analysis/export`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ results })
    });
    if (!res.ok) {
      const err = await res.json().catch(()=>({error: res.statusText}));
      throw new Error(err?.details || err?.error || `Export failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = pickFilenameFromHeaders(res, 'analysis_export.zip');
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  async function downloadHtmlReport(results) {
    const res = await fetch(`${API_BASE}/api/statistical-analysis/report`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ results })
    });
    if (!res.ok) {
      const err = await res.json().catch(()=>({error: res.statusText}));
      throw new Error(err?.details || err?.error || `Report failed (${res.status})`);
    }
    const blob = await res.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = pickFilenameFromHeaders(res, 'analysis_report.html');
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }

  // New: create share link (DigitalOcean-ready)
  async function createShareLink(results) {
    const res = await fetch(`${API_BASE}/api/statistical-analysis/share`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ results })
    });
    if (!res.ok) {
      const err = await res.json().catch(()=>null);
      throw new Error(err?.error || `Share link failed (${res.status})`);
    }
    const data = await res.json();
    if (!data?.url) throw new Error('Share endpoint did not return a URL');
    try {
      await navigator.clipboard.writeText(data.url);
      showToast('Share link copied to clipboard', 'success');
    } catch {
      window.prompt('Copy your share link:', data.url);
      showToast('Share link ready', 'success');
    }
  }

  const downloadCsv = (filename, csv) => {
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = filename;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const tableStyle = { width: '100%', borderCollapse: 'collapse' };
  const cell = { border: '1px solid #e2e2e2', padding: '8px', textAlign: 'right' };
  const cellLeft = { ...cell, textAlign: 'left' };
  const cellHdr = { ...cell, background: '#fafafa', fontWeight: 600 };

  const applyAnalysisResults = (payload) => {
    const data = payload || {};
    setAnalysisResults(data);
    const firstTab = ALL_TABS.find((t) => data[t]);
    if (firstTab) {
      setActiveResultTab(firstTab);
      setResultsPanelOpen(true);
    }
  };

  // ---------- Renderers ----------
  const renderDescriptiveStats = (descObj) => {
    if (!descObj || typeof descObj !== 'object') return <div>No descriptive statistics available.</div>;
    const cols = Object.keys(descObj);
    if (!cols.length) return <div>No descriptive statistics available.</div>;
    const metrics = Array.from(new Set(cols.flatMap((c) => Object.keys(descObj[c] || {}))));
    return (
      <div>
        <h4 style={{ margin: '8px 0 12px' }}>Descriptive Statistics</h4>
        <table style={tableStyle} aria-label="Descriptive statistics table">
          <thead>
            <tr>
              <th style={{ ...cellHdr, textAlign: 'left' }}>Metric</th>
              {cols.map((c) => (
                <th key={c} style={cellHdr}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {metrics.map((m) => (
              <tr key={m}>
                <td style={cellLeft}>{m}</td>
                {cols.map((c) => (
                  <td key={`${c}-${m}`} style={cell}>{fmtNum(descObj[c]?.[m])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderCorrelations = (corrObj) => {
    if (!corrObj || typeof corrObj !== 'object') return <div>No correlation data available.</div>;
    const cols = Object.keys(corrObj);
    if (!cols.length) return <div>No correlation data available.</div>;
    return (
      <div>
        <h4 style={{ margin: '8px 0 12px' }}>Correlation Matrix (Pearson)</h4>
        <table style={tableStyle} aria-label="Correlation matrix">
          <thead>
            <tr>
              <th style={{ ...cellHdr, textAlign: 'left' }}>Variable</th>
              {cols.map((c) => (
                <th key={`h-${c}`} style={cellHdr}>{c}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cols.map((row) => (
              <tr key={`r-${row}`}>
                <td style={cellLeft}>{row}</td>
                {cols.map((col) => (
                  <td key={`${row}-${col}`} style={cell}>{fmtNum(corrObj[row]?.[col])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderAnova = (anova) => {
    if (!anova) return <div>No ANOVA available.</div>;
    const labels = Object.keys(anova.group_means || {});
    return (
      <div>
        <h4 style={{ margin: '8px 0 12px' }}>
          One-way ANOVA — target: <code>{anova.target}</code>, group: <code>{anova.group}</code>
        </h4>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
          <div className={styles.statCard}><div>F</div><div>{fmtNum(anova.f_stat)}</div></div>
          <div className={styles.statCard}><div>p</div><div>{fmtNum(anova.p_value)}</div></div>
          <div className={styles.statCard}><div>η²</div><div>{fmtNum(anova.eta_squared)}</div></div>
        </div>

        <h5 style={{ margin: '8px 0 8px' }}>Group Means & Counts</h5>
        <table style={tableStyle} aria-label="ANOVA group summary">
          <thead>
            <tr>
              <th style={{ ...cellHdr, textAlign: 'left' }}>{anova.group}</th>
              <th style={cellHdr}>Mean ({anova.target})</th>
              <th style={cellHdr}>Count</th>
            </tr>
          </thead>
          <tbody>
            {labels.map((lbl) => (
              <tr key={lbl}>
                <td style={cellLeft}>{lbl}</td>
                <td style={cell}>{fmtNum(anova.group_means?.[lbl])}</td>
                <td style={cell}>{fmtNum(anova.group_counts?.[lbl])}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  };

  const renderTTest = (tt) => {
    if (!tt) return <div>No T-Test available (requires exactly two groups).</div>;
    const [g1, g2] = tt.groups || [];
    return (
      <div>
        <h4 style={{ margin: '8px 0 12px' }}>
          Two-sample T-Test — target: <code>{tt.target}</code>, group: <code>{tt.group}</code>
        </h4>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 12, marginBottom: 12 }}>
          <div className={styles.statCard}><div>t</div><div>{fmtNum(tt.t_stat)}</div></div>
          <div className={styles.statCard}><div>p</div><div>{fmtNum(tt.p_value)}</div></div>
          <div className={styles.statCard}><div>Cohen&apos;s d</div><div>{fmtNum(tt.cohens_d)}</div></div>
          <div className={styles.statCard}><div>Equal Var</div><div>{String(tt.equal_var_assumed)}</div></div>
        </div>

        <details style={{ marginBottom: 12 }}>
          <summary>Variance check (Levene)</summary>
          <div style={{ marginTop: 8 }}>
            <div>Levene stat: {fmtNum(tt.levene_stat)}</div>
            <div>Levene p: {fmtNum(tt.levene_p)}</div>
          </div>
        </details>

        {g1 && g2 ? (
          <>
            <h5 style={{ margin: '8px 0 8px' }}>Group Summary</h5>
            <table style={tableStyle} aria-label="T-Test group summary">
              <thead>
                <tr>
                  <th style={{ ...cellHdr, textAlign: 'left' }}>{tt.group}</th>
                  <th style={cellHdr}>Mean ({tt.target})</th>
                  <th style={cellHdr}>Count</th>
                </tr>
              </thead>
              <tbody>
                {[g1, g2].map((g) => (
                  <tr key={g}>
                    <td style={cellLeft}>{g}</td>
                    <td style={cell}>{fmtNum(tt.group_means?.[g])}</td>
                    <td style={cell}>{fmtNum(tt.group_counts?.[g])}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : null}
      </div>
    );
  };

  const renderGenericJson = (data, title = 'Results') => (
    <div>
      <h4 style={{ margin: '8px 0 12px' }}>{title}</h4>
      <pre style={{ background: '#0f172a0d', padding: 12, borderRadius: 6, overflowX: 'auto' }}>
        {JSON.stringify(data, null, 2)}
      </pre>
    </div>
  );

  // ---------- API ----------
  async function uploadPreview(file) {
    const form = new FormData();
    form.append('file', file);
    const res = await fetch(`${API_BASE}/api/statistical-analysis/upload`, {
      method: 'POST',
      body: form,
      credentials: 'include',
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(`Upload preview failed: ${res.status} ${t}`);
    }
    const payload = await res.json();
    if (!payload?.success) throw new Error(payload?.error || 'Upload preview error');

    const preview = payload.data || {};
    setDatasetInfo(preview);

    const ci = Array.isArray(preview.column_info) ? preview.column_info : [];
    const nums = ci.filter(c => c.type === 'numeric').map(c => c.name);
    const cats = ci.filter(c => c.type === 'categorical').map(c => c.name);
    setNumericCols(nums);
    setCategoricalCols(cats);

    const msgLines = [
      `Loaded **${preview.filename || file.name}** (${preview.rows} rows, ${preview.columns} columns).`,
      `Numeric: ${nums.length ? nums.join(', ') : '—'}.`,
      `Categorical: ${cats.length ? cats.join(', ') : '—'}.`
    ];
    setMessages(prev => [
      ...prev,
      { role: 'assistant', content: msgLines.join(' '), timestamp: new Date() }
    ]);

    return { nums, cats, preview };
  }

  async function runComprehensive(file, { goal = 'describe', target = '', group = '' } = {}, _internal = { rerun: false }) {
    setIsLoading(true);
    try {
      const form = new FormData();
      form.append('file', file);
      if (goal) form.append('goal', goal);
      if (target) form.append('target_col', target);
      if (group)  form.append('group_col', group);

      const res = await fetch(`${API_BASE}/api/statistical-analysis/comprehensive`, {
        method: 'POST',
        body: form,
        credentials: 'include',
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Comprehensive analysis failed: ${res.status} ${text}`);
      }

      const payload = await res.json();
      if (!payload?.success) throw new Error(payload?.error || 'Unknown analysis error');

      const { results } = payload || {};
      rawResultsRef.current = results; // keep full results for export/report

      const tabs = {};
      if (results?.analysis?.descriptive_stats) tabs['Descriptive Stats'] = results.analysis.descriptive_stats;
      if (results?.analysis?.correlations)      tabs['Correlations']     = results.analysis.correlations;
      if (results?.analysis?.anova)             tabs['ANOVA']            = results.analysis.anova;
      if (results?.analysis?.t_test)            tabs['T-Test']           = results.analysis.t_test;
      if (results?.analysis?.chi_square)        tabs['Chi-Square']       = results.analysis.chi_square;
      if (results?.analysis?.regression)        tabs['Regression']       = results.analysis.regression;

      applyAnalysisResults(tabs);

      if (results?.dataset_info) {
        setDatasetInfo(results.dataset_info);
        const nums = results.dataset_info.numeric_columns || [];
        const cats = results.dataset_info.categorical_columns || [];
        setNumericCols(nums);
        setCategoricalCols(cats);

        const needGroupTests = !results?.analysis?.anova && !results?.analysis?.t_test;
        if (needGroupTests && !_internal.rerun) {
          if (nums.length === 1 && cats.length === 1) {
            setLastTarget(nums[0]); setLastGroup(cats[0]);
            await runComprehensive(file, { goal: 'explore', target: nums[0], group: cats[0] }, { rerun: true });
          } else if (nums.length >= 1 && cats.length >= 1) {
            setPickerTarget(nums[0] || '');
            setPickerGroup(cats[0] || '');
            setShowPicker(true);
            setMessages(prev => [
              ...prev,
              {
                role: 'assistant',
                content: `I can run ANOVA/T-Test if you confirm columns. Use the Columns button or type: "anova <numeric> by <categorical>"`,
                timestamp: new Date()
              }
            ]);
          }
        }
      }

      if (results?.ai_insights) {
        setMessages(prev => [...prev, { role: 'assistant', content: results.ai_insights, timestamp: new Date() }]);
      }

      if (target) setLastTarget(target);
      if (group) setLastGroup(group);

      // Build & save a restore snapshot
      const activeTab = ALL_TABS.find((t) => tabs[t]) || null;
      const snapshot = {
        tabs,
        raw: results,
        activeTab,
        target: target || lastTarget || '',
        group: group || lastGroup || ''
      };

      // Update UI history
      const historyItem = {
        client_id: `${Date.now()}_${Math.random().toString(36).slice(2)}`,
        title: file.name,
        date: new Date().toLocaleString(),
        testsCount: Object.keys(tabs).filter(k => !!tabs[k]).length,
        snapshot
      };
      setAnalysisHistory(prev => [historyItem, ...prev]);
      saveLocalHistory([historyItem, ...loadLocalHistory()]);

      // Persist history server-side (upsert by client_id) with snapshot
      try {
        await saveStatsHistoryItem({
          client_id: historyItem.client_id,
          title: historyItem.title,
          date: historyItem.date,
          testsCount: historyItem.testsCount,
          snapshot
        });
      } catch (e) {
        console.debug('stats history save skipped', e);
      }

      showToast('Analysis complete', 'success');
    } catch (e) {
      showToast(e.message || 'Analysis failed', 'error');
      throw e;
    } finally {
      setIsLoading(false);
    }
  }

  async function sendAiChat(message, context = {}) {
    const res = await fetch(`${API_BASE}/api/statistical-analysis/ai-chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ message, context }),
    });
    if (!res.ok) {
      const text = await res.text();
      throw new Error(`AI chat failed: ${res.status} ${text}`);
    }
    const payload = await res.json();
    if (!payload?.success) throw new Error(payload?.error || 'Unknown AI error');
    return payload.response;
  }

  // ---------- Handlers ----------
  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    const name = file?.name?.toLowerCase() || '';
    const ok = name.endsWith('.csv') || name.endsWith('.xlsx') || name.endsWith('.xls');
    if (!file || !ok) return;

    setUploadedFile(file);
    setLastFile(file);
    setShowPicker(false);
    setLastTarget(''); setLastGroup('');

    setMessages((prev) => [
      ...prev,
      { role: 'user', type: 'file', fileName: file.name, fileSize: file.size, timestamp: new Date() }
    ]);

    try {
      setIsLoading(true);
      await uploadPreview(file);
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Running initial analysis…`, timestamp: new Date() }
      ]);
      await runComprehensive(file, { goal: 'describe' });
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Analysis failed: ${err?.message || 'Unknown error'}`, timestamp: new Date() }
      ]);
      console.error(err);
    } finally {
      setIsLoading(false);
    }
  };

  const runQuickPrompt = async (which) => {
    if (!lastFile) {
      showToast('Upload a file first', 'warning');
      fileInputRef.current?.click();
      return;
    }
    try {
      if (which === 'describe') {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Running descriptive statistics…', timestamp: new Date() }]);
        await runComprehensive(lastFile, { goal: 'describe' });
      } else if (which === 'correlate') {
        setMessages(prev => [...prev, { role: 'assistant', content: 'Exploring correlations…', timestamp: new Date() }]);
        await runComprehensive(lastFile, { goal: 'explore' });
      } else if (which === 'compare') {
        const num = numericCols[0];
        const cat = categoricalCols[0];
        if (num && cat) {
          setMessages(prev => [...prev, { role: 'assistant', content: `Comparing ${num} by ${cat}…`, timestamp: new Date() }]);
          await runComprehensive(lastFile, { goal: 'explore', target: num, group: cat });
        } else {
          setShowPicker(true);
          showToast('Choose columns for ANOVA/T-Test', 'info');
        }
      }
    } catch (e) {
      showToast(e.message || 'Quick action failed', 'error');
    }
  };

  const handleSendMessage = async () => {
    const msg = inputValue.trim();
    if (!msg || isLoading) return;

    setMessages((prev) => [...prev, { role: 'user', content: msg, timestamp: new Date() }]);
    setInputValue('');

    // Robust command parsing
    const cmd = (() => {
      const quoted = /\b(anova|t[\-\s]?test|ttest)\b\s+"([^"]+)"\s+by\s+"([^"]+)"/i;
      const m1 = msg.match(quoted);
      if (m1) return { test: m1[1], target: m1[2].trim(), group: m1[3].trim() };

      const loose = /\b(anova|t[\-\s]?test|ttest)\b\s+(.+?)\s+by\s+(.+)/i;
      const m2 = msg.match(loose);
      if (m2) {
        const unquote = (s) => s.trim().replace(/^"(.*)"$/, '$1');
        return { test: m2[1], target: unquote(m2[2]), group: unquote(m2[3]) };
      }
      return null;
    })();

    if (cmd && lastFile) {
      const { test, target, group } = cmd;
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `Running ${test.toUpperCase()} for ${target} by ${group}…`, timestamp: new Date() }
      ]);
      try {
        await runComprehensive(lastFile, { goal: 'explore', target, group });
        setShowPicker(false);
        return;
      } catch (err) {
        setMessages((prev) => [
          ...prev,
          { role: 'assistant', content: `Run failed: ${err?.message || 'Unknown error'}`, timestamp: new Date() }
        ]);
      }
    }

    // Fallback -> AI helper
    try {
      const context = {
        availableTabs: Object.keys(analysisResults || {}),
        numericCols,
        categoricalCols,
      };
      const aiReply = await sendAiChat(msg, context);
      setMessages((prev) => [...prev, { role: 'assistant', content: aiReply || 'Done.', timestamp: new Date() }]);
    } catch (err) {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', content: `AI error: ${err?.message || 'Unknown error'}`, timestamp: new Date() }
      ]);
      console.error(err);
    }
  };

  const handleRunPicker = async () => {
    if (!lastFile || !pickerTarget || !pickerGroup || isLoading) return;
    setMessages((prev) => [...prev, { role: 'assistant', content: `Running ANOVA/T-Test for ${pickerTarget} by ${pickerGroup}…`, timestamp: new Date() }]);
    try {
      await runComprehensive(lastFile, { goal: 'explore', target: pickerTarget, group: pickerGroup });
      setLastTarget(pickerTarget);
      setLastGroup(pickerGroup);
      setShowPicker(false);
    } catch (err) {
      setMessages((prev) => [...prev, { role: 'assistant', content: `Run failed: ${err?.message || 'Unknown error'}`, timestamp: new Date() }]);
    }
  };

  const handleRerunSame = async () => {
    if (!lastFile || !lastTarget || !lastGroup || isLoading) return;
    setMessages((prev) => [...prev, { role: 'assistant', content: `Re-running for ${lastTarget} by ${lastGroup}…`, timestamp: new Date() }]);
    await runComprehensive(lastFile, { goal: 'explore', target: lastTarget, group: lastGroup }, { rerun: true });
  };

  const handleResultTabClick = (tabName) => {
    setActiveResultTab(tabName);
    setResultsPanelOpen(true);
  };

  const closeResultsPanel = () => {
    setResultsPanelOpen(false);
    setActiveResultTab(null);
  };

  // Per-tab CSV export
  const handleExportAnalysis = () => {
    if (!activeResultTab) return;
    const data = analysisResults[activeResultTab];
    const csv = makeCsvForTab(activeResultTab, data);
    if (!csv) {
      showToast('Nothing to export for this tab', 'warning');
      return;
    }
    const base = (uploadedFile?.name || 'analysis').replace(/\.[^.]+$/, '');
    downloadCsv(`${base}_${activeResultTab.replace(/\s+/g, '_').toLowerCase()}.csv`, csv);
    showToast('CSV exported', 'success');
  };

  // Backend ZIP export (all analyses)
  const handleExportZipAll = async () => {
    try {
      if (!rawResultsRef.current) throw new Error('No results available to export');
      const payload = buildResultsForDownload(shareIncludeInsights);
      await downloadExportZip(payload);
      showToast('Export ZIP ready', 'success');
    } catch (e) {
      showToast(e.message || 'Export failed', 'error');
    }
  };

  // Backend HTML report (all analyses)
  const handleGenerateReport = async () => {
    try {
      if (!rawResultsRef.current) throw new Error('No results available for report');
      const payload = buildResultsForDownload(shareIncludeInsights);
      await downloadHtmlReport(payload);
      showToast('Report generated', 'success');
    } catch (e) {
      showToast(e.message || 'Report failed', 'error');
    }
  };

  // Copy shareable link
  const handleCopyShareLink = async () => {
    try {
      if (!rawResultsRef.current) throw new Error('No results available to share');
      const payload = buildResultsForDownload(shareIncludeInsights);
      try {
        await createShareLink(payload);
      } catch (apiErr) {
        if (navigator.share) {
          await navigator.share({
            title: 'Analysis results',
            text: 'Analysis results (export HTML for a portable copy).',
            url: window.location.href
          });
          showToast('Shared via device share sheet', 'success');
        } else {
          showToast('Share service not configured. Ask backend to add /share.', 'warning');
        }
      }
    } catch (e) {
      showToast(e.message || 'Share failed', 'error');
    } finally {
      setShareOpen(false);
    }
  };

  const handleDeleteHistoryItem = async (item) => {
    if (!item?.client_id) return;
    await deleteStatsHistoryItem(item.client_id);
    setAnalysisHistory(prev => prev.filter(p => p.client_id !== item.client_id));
    showToast('Removed from history', 'success');
  };

  const restoreFromSnapshot = (snapshot) => {
    if (!snapshot || !snapshot.tabs) {
      showToast('This entry has no saved snapshot to restore.', 'warning');
      return;
    }
    applyAnalysisResults(snapshot.tabs);
    rawResultsRef.current = snapshot.raw || null;
    setActiveResultTab(snapshot.activeTab || ALL_TABS.find(t => snapshot.tabs[t]) || null);
    setLastTarget(snapshot.target || '');
    setLastGroup(snapshot.group || '');
    setResultsPanelOpen(true);
    showToast('Restored previous session', 'success');
  };

  const handleHistorySelect = async (item) => {
    // Prefer local snapshot immediately
    if (item?.snapshot) {
      restoreFromSnapshot(item.snapshot);
      return;
    }
    // Try backend fetch for the full item (expecting snapshot/raw)
    const data = await fetchStatsHistoryItem(item.client_id);
    if (data?.snapshot) {
      restoreFromSnapshot(data.snapshot);
      // also patch local cache for next time
      setAnalysisHistory(prev =>
        prev.map(h => (h.client_id === item.client_id ? { ...h, snapshot: data.snapshot } : h))
      );
      saveLocalHistory(loadLocalHistory().map(h => (h.client_id === item.client_id ? { ...h, snapshot: data.snapshot } : h)));
      return;
    }
    // If backend returns raw results in a different shape, try to coerce
    if (data?.results || data?.raw || data?.tabs) {
      const tabs = data.tabs || {};
      const snap = {
        tabs: Object.keys(tabs).length ? tabs : null,
        raw: data.raw || data.results || null,
        activeTab: data.activeTab || (Object.keys(tabs).find(t => tabs[t]) || null),
        target: data.target || '',
        group: data.group || ''
      };
      if (snap.tabs) {
        restoreFromSnapshot(snap);
        setAnalysisHistory(prev =>
          prev.map(h => (h.client_id === item.client_id ? { ...h, snapshot: snap } : h))
        );
        saveLocalHistory(loadLocalHistory().map(h => (h.client_id === item.client_id ? { ...h, snapshot: snap } : h)));
        return;
      }
    }
    showToast('Could not restore this entry (no snapshot available).', 'warning');
  };

  if (!adminSettings?.guidedModeEnabled) {
    return (
      <div style={{ padding: '40px', textAlign: 'center' }}>
        <h2>Statistics Tool Disabled</h2>
        <p>This tool has been disabled by your administrator.</p>
        <button
          onClick={() => navigate('/profile')}
          style={{ marginTop: 20, padding: '10px 20px' }}
        >
          ← Back to Dashboard
        </button>
      </div>
    );
  }

  const ColumnPicker = () => {
    if (!showPicker) return null;
    return (
      <div className={styles.pickerPanel} style={{ padding: 12, borderTop: '1px solid #eee' }}>
        <h4 style={{ margin: '0 0 8px' }}>Choose columns for ANOVA/T-Test</h4>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
          <label>
            Target (numeric):&nbsp;
            <select value={pickerTarget} onChange={(e) => setPickerTarget(e.target.value)} disabled={isLoading}>
              <option value="">Select</option>
              {numericCols.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <label>
            Group (categorical):&nbsp;
            <select value={pickerGroup} onChange={(e) => setPickerGroup(e.target.value)} disabled={isLoading}>
              <option value="">Select</option>
              {categoricalCols.map((c) => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
          </label>
          <button className={styles.btn} onClick={handleRunPicker} disabled={!pickerTarget || !pickerGroup || isLoading}>
            {isLoading ? 'Running…' : 'Run'}
          </button>
          <button className={styles.btn} onClick={() => setShowPicker(false)} disabled={isLoading}>
            Close
          </button>
        </div>
        {datasetInfo ? (
          <div style={{ marginTop: 8, fontSize: 12, opacity: 0.8 }}>
            <div><strong>Numeric:</strong> {numericCols.join(', ') || '—'}</div>
            <div><strong>Categorical:</strong> {categoricalCols.join(', ') || '—'}</div>
          </div>
        ) : null}
      </div>
    );
  };

  const LoadingBar = () => (
    isLoading ? (
      <div style={{ padding: '8px 12px', borderTop: '1px solid #eee', display: 'flex', alignItems: 'center', gap: 8 }}>
        <span className={styles.spinner} aria-hidden="true" />
        <span>Crunching numbers…</span>
      </div>
    ) : null
  );

  const Toast = () => (
    toast.open ? (
      <div
        className={styles.toast}
        role="status"
        aria-live="polite"
        style={{
          position: 'fixed',
          bottom: 16,
          right: 16,
          padding: '10px 14px',
          borderRadius: 8,
          boxShadow: '0 6px 24px rgba(0,0,0,0.12)',
          background: toast.kind === 'error' ? '#fee2e2'
                    : toast.kind === 'success' ? '#dcfce7'
                    : toast.kind === 'warning' ? '#fef9c3'
                    : '#eef2ff',
          color: '#111',
          zIndex: 9999,
          maxWidth: 420
        }}
      >
        {toast.text}
      </div>
    ) : null
  );

  return (
    <>
      <div className={styles.statsContainer}>
        {/* Left History Sidebar */}
        <div className={`${styles.historySidebar} ${historySidebarOpen ? styles.open : ''}`}>
          <div className={styles.historyHeader}>
            <h3>
              <i className="fas fa-history" /> History
            </h3>
            <button
              className={styles.closeSidebarBtn}
              onClick={() => setHistorySidebarOpen(false)}
              aria-label="Close history"
              title="Close history"
            >
              <i className="fas fa-times" />
            </button>
          </div>

          <div className={styles.historyList}>
            {analysisHistory.length === 0 ? (
              <div className={styles.emptyHistory}>
                <i className="fas fa-inbox" />
                <p>No previous analyses yet</p>
              </div>
            ) : (
              analysisHistory.map((item) => (
                <div
                  key={item.client_id}
                  className={styles.historyItem}
                  onClick={(e) => {
                    // avoid click when pressing the trash button
                    if (e.target.closest(`.${styles.historyDeleteBtn}`)) return;
                    handleHistorySelect(item);
                  }}
                  role="button"
                  tabIndex={0}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleHistorySelect(item); }}
                  title="Restore this session"
                >
                  <div className={styles.historyItemTitle}>{item.title}</div>
                  <div className={styles.historyItemMeta}>
                    <span>
                      <i className="fas fa-calendar" /> {item.date}
                    </span>
                    <span>
                      <i className="fas fa-chart-line" /> {item.testsCount} Tests
                    </span>
                  </div>
                  <button
                    className={styles.historyDeleteBtn}
                    onClick={(e) => { e.stopPropagation(); handleDeleteHistoryItem(item); }}
                    title="Remove from history"
                    aria-label="Remove from history"
                  >
                    <i className="fas fa-trash" />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>

        {/* Left Edge History Toggle */}
        <button
          className={`${styles.historyToggleBtn} ${historySidebarOpen ? styles.historyToggleOpen : ''}`}
          onClick={() => setHistorySidebarOpen((s) => !s)}
          aria-label={historySidebarOpen ? 'Close history' : 'Open history'}
          title={historySidebarOpen ? 'Close history' : 'Open history'}
          disabled={isLoading}
        >
          <i className={`fas ${historySidebarOpen ? 'fa-times' : 'fa-history'}`} />
        </button>

        {/* Main Content */}
        <div
          className={[
            styles.mainContent,
            historySidebarOpen ? styles.historyOpen : '',
            resultsPanelOpen ? styles.resultsOpen : ''
          ].join(' ')}
        >
          {/* Centered header with Logout (left) and Share (right) */}
          <div className={styles.topHeader} style={{ position: 'relative', minHeight: 60 }}>
            {/* Logout link - upper left (simple link, with spacing) */}
            <div style={{ position: 'absolute', left: 16, top: '50%', transform: 'translateY(-50%)' }}>
              <a href="/logout" className={styles.link} title="Logout" aria-label="Logout">← Logout</a>
            </div>

            {/* Centered title/subtitle */}
            <div style={{ textAlign: 'center', margin: '0 auto' }}>
              <h1 style={{ margin: 0 }}>Statistical Analysis Workspace</h1>
              <div className={styles.headerSubtitle}>
                AI-powered statistical analysis with conversational guidance
              </div>
            </div>

            {/* Share button & dropdown - upper right, pulled in from under tabs */}
            <div
              className={styles.headerRight}
              ref={shareWrapperRef}
              style={{ position: 'absolute', right: 'var(--tabs-gutter)', top: '50%', transform: 'translateY(-50%)', zIndex: 160 }}
            >
              <button
                className={styles.btn}
                onClick={() => setShareOpen(o => !o)}
                disabled={isLoading || !rawResultsRef.current}
                title="Share & export"
              >
                <i className="fas fa-share-alt" /> Share
              </button>

              {shareOpen && (
                <div
                  className={styles.dropdown}
                  style={{
                    position: 'absolute',
                    right: 0,
                    top: '100%',
                    marginTop: 8,
                    minWidth: 280,
                    background: '#fff',
                    border: '1px solid #e5e7eb',
                    borderRadius: 8,
                    boxShadow: '0 12px 24px rgba(0,0,0,0.12)',
                    zIndex: 170,
                    padding: 10
                  }}
                >
                  <label style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px' }}>
                    <input
                      type="checkbox"
                      checked={shareIncludeInsights}
                      onChange={e => setShareIncludeInsights(e.target.checked)}
                    />
                    Include AI insights
                  </label>

                  <hr style={{ border: 'none', borderTop: '1px solid #eee', margin: '6px 0' }} />

                  <button
                    className={styles.menuItem}
                    onClick={handleCopyShareLink}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', padding: '8px 10px', textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    <i className="fas fa-link" /> Copy Share Link
                  </button>

                  <button
                    className={styles.menuItem}
                    onClick={() => { setShareOpen(false); handleGenerateReport(); }}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', padding: '8px 10px', textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    <i className="fas fa-file-alt" /> Download Report (HTML)
                  </button>

                  <button
                    className={styles.menuItem}
                    onClick={() => { setShareOpen(false); handleExportZipAll(); }}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', padding: '8px 10px', textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    <i className="fas fa-file-archive" /> Download ZIP (CSVs)
                  </button>

                  <button
                    className={styles.menuItem}
                    onClick={() => { setShareOpen(false); showToast('PDF coming soon. Use “Download Report (HTML)” then print to PDF.', 'info'); }}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', padding: '8px 10px', textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    <i className="fas fa-file-pdf" /> Download PDF
                  </button>

                  <button
                    className={styles.menuItem}
                    onClick={() => { setShareOpen(false); showToast('Word coming soon.', 'info'); }}
                    style={{ display: 'flex', gap: 8, alignItems: 'center', width: '100%', padding: '8px 10px', textAlign: 'left', background: 'transparent', border: 'none', cursor: 'pointer' }}
                  >
                    <i className="fas fa-file-word" /> Download Word
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Chat Area */}
          <div className={styles.chatArea}>
            <div className={`${styles.chatMessages} ${styles.chatGutter}`} ref={chatMessagesRef}>
              {messages.length === 0 ? (
                <div className={styles.welcomeScreen}>
                  <h2>What would you like to analyze?</h2>
                  <p>
                    Upload your data and I&apos;ll help you run the right statistical
                    tests, interpret results, and provide insights.
                  </p>
                  <div className={styles.suggestionCards}>
                    <button
                      className={styles.suggestionCard}
                      onClick={() => runQuickPrompt('correlate')}
                      title="Explore correlations"
                    >
                      Analyze sales data to find correlations between price and revenue
                    </button>
                    <button
                      className={styles.suggestionCard}
                      onClick={() => runQuickPrompt('compare')}
                      title="Compare groups (ANOVA/T-Test)"
                    >
                      Compare customer satisfaction scores across different regions
                    </button>
                    <button
                      className={styles.suggestionCard}
                      onClick={() => runQuickPrompt('describe')}
                      title="Descriptive statistics"
                    >
                      Run descriptive statistics on product performance metrics
                    </button>
                  </div>
                </div>
              ) : (
                messages.map((msg, idx) => (
                  <div key={idx} className={`${styles.message} ${styles[msg.role]}`}>
                    <div className={styles.messageAvatar}>
                      {msg.role === 'assistant' ? 'K' : 'U'}
                    </div>

                    {msg.type === 'file' ? (
                      <div className={styles.fileUploadMessage}>
                        <div className={styles.fileIcon}>
                          <i className="fas fa-file-csv" />
                        </div>
                        <div className={styles.fileInfo}>
                          <div className={styles.fileName}>{msg.fileName}</div>
                          <div className={styles.fileMeta}>
                            {Math.round(msg.fileSize / 1024)} KB • Uploaded just now
                          </div>
                        </div>
                      </div>
                    ) : (
                      <div className={styles.messageBubble}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>
                          {String(msg.content || '')}
                        </ReactMarkdown>
                      </div>
                    )}
                  </div>
                ))
              )}
            </div>

            {/* Loading bar */}
            <LoadingBar />

            {/* Column picker */}
            <ColumnPicker />

            {/* Chat Input */}
            <div className={`${styles.chatInputArea} ${styles.chatGutter}`}>
              <div className={styles.chatInputWrapper}>
                <button
                  className={styles.uploadBtnChat}
                  onClick={() => !isLoading && fileInputRef.current?.click()}
                  title="Upload CSV/Excel"
                  aria-label="Upload CSV/Excel"
                  disabled={isLoading}
                >
                  <i className="fas fa-paperclip" />
                </button>

                <input
                  ref={fileInputRef}
                  type="file"
                  accept=".csv,.xlsx,.xls"
                  onChange={handleFileUpload}
                  style={{ display: 'none' }}
                  disabled={isLoading}
                />

                <textarea
                  className={styles.chatInput}
                  placeholder="Describe your analysis or type: anova revenue by region"
                  rows={1}
                  value={inputValue}
                  onChange={(e) => setInputValue(e.target.value)}
                  onKeyDown={(e) => {
                    if (!isLoading && e.key === 'Enter' && !e.shiftKey) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  disabled={isLoading}
                />

                <button
                  className={styles.sendBtn}
                  onClick={handleSendMessage}
                  disabled={isLoading || !inputValue.trim()}
                >
                  <i className="fas fa-paper-plane" />
                </button>
              </div>
            </div>
          </div>
        </div>

        {/* Right Tabs */}
        <div className={styles.resultsTabsContainer}>
          {ALL_TABS.map((tab) => {
            const isActive = activeResultTab === tab;
            const hasData = tabHasData(tab);
            return (
              <div
                key={tab}
                className={[
                  styles.verticalTab,
                  isActive ? styles.active : '',
                  hasData ? styles.hasData : ''
                ].join(' ')}
                onClick={() => !isLoading && handleResultTabClick(tab)}
                role="button"
                aria-label={tab}
                aria-pressed={isActive}
                title={hasData ? `${tab} (ready)` : `${tab} (no data yet)`}
              >
                {hasData && <span className={styles.dataDot} aria-hidden="true" />}
                {tab}
              </div>
            );
          })}
        </div>

        {/* Results Panel */}
        <div className={`${styles.resultsPanel} ${resultsPanelOpen ? styles.open : ''}`}>
          <button
            className={styles.resultsCloseCorner}
            onClick={closeResultsPanel}
            aria-label="Close results"
            title="Close results"
          >
            <i className="fas fa-times" />
          </button>

          <div className={styles.resultsHeader}>
            <h3>
              <i className="fas fa-chart-bar" /> {activeResultTab || 'Analysis Results'}
            </h3>

            <div className={styles.resultsHeaderActions}>
              {(numericCols.length && categoricalCols.length) ? (
                <button className={styles.btn} onClick={() => setShowPicker(s => !s)} disabled={isLoading}>
                  <i className="fas fa-sliders-h" /> Columns
                </button>
              ) : null}

              {lastFile && lastTarget && lastGroup ? (
                <button className={styles.btn} onClick={handleRerunSame} disabled={isLoading}>
                  <i className="fas fa-sync" /> Re-run
                </button>
              ) : null}

              <button className={styles.btn} onClick={handleGenerateReport} disabled={isLoading || !rawResultsRef.current}>
                <i className="fas fa-file-alt" /> Report
              </button>

              <button
                className={styles.btn}
                onClick={handleExportZipAll}
                disabled={isLoading || !rawResultsRef.current}
              >
                <i className="fas fa-file-archive" /> Export ZIP
              </button>

              <button
                className={styles.btn}
                onClick={handleExportAnalysis}
                disabled={isLoading || !activeResultTab || !analysisResults[activeResultTab]}
              >
                <i className="fas fa-download" /> Export CSV
              </button>
            </div>
          </div>

          <div className={styles.resultsContent}>
            {activeResultTab && analysisResults[activeResultTab] ? (
              (() => {
                const data = analysisResults[activeResultTab];
                switch (activeResultTab) {
                  case 'Descriptive Stats':
                    return renderDescriptiveStats(data);
                  case 'Correlations':
                    return renderCorrelations(data);
                  case 'ANOVA':
                    return renderAnova(data);
                  case 'T-Test':
                    return renderTTest(data);
                  case 'Regression':
                  case 'Chi-Square':
                    return renderGenericJson(data, activeResultTab);
                  default:
                    return renderGenericJson(data, activeResultTab);
                }
              })()
            ) : (
              <div className={styles.emptyResults}>
                <i className="fas fa-chart-bar" />
                <p>Run an analysis to see results here</p>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Toast */}
      <Toast />

      {showReportsModal && (
        <ReportsModal
          isOpen={showReportsModal}
          onClose={() => setShowReportsModal(false)}
        />
      )}
    </>
  );
};

export default Statistics;
