// ============================================================================
// File: src/lib/MarketIQClient.jsx
// Purpose: Robust client incl. scenarios, unified chat, and stable session SID
//          + NEW endpoints: analyses, scenarios (CRUD), bundle
//          (keeps legacy shapes; falls back where needed)
// ============================================================================

import { API_BASE } from '../../config/apiBase';

export const endpoints = {
  // AI Agent endpoints (NEW)
  convoStart:     `${API_BASE}/api/ai-agent/conversation/start`,
  convoNext:      `${API_BASE}/api/ai-agent/conversation/continue`,
  analyze:        `${API_BASE}/api/ai-agent/analyze`,
  readinessSpec:  `${API_BASE}/api/ai-agent/readiness/spec`,
  readinessAudit: (threadId) => `${API_BASE}/api/ai-agent/readiness/audit?thread_id=${encodeURIComponent(threadId)}`,
  
  // Threads
  getThread:      (threadId) => `${API_BASE}/api/ai-agent/threads/${encodeURIComponent(threadId)}`,
  
  // Analyses
  listAnalyses:   (threadId) => `${API_BASE}/api/ai-agent/threads/${encodeURIComponent(threadId)}/analyses`,
  
  // Legacy chat (keep for now)
  chat:       `${API_BASE}/api/ai-agent/conversation/continue`,
  chatStream: `${API_BASE}/api/chat/stream`,

  // PROMPT ALIGNMENT: Endpoint for beginning a project from a scorecard
  beginProject: `${API_BASE}/api/projects/generate/ai`,
  
  // KEEP OLD ENDPOINTS for backward compat during migration
  threadBundle:   (threadId, msg = 50, scn = 50 ) =>
    `${API_BASE}/api/market-iq/threads/${encodeURIComponent(threadId)}/bundle?msg_limit=${msg}&scn_limit=${scn}`,
  scenario:   `${API_BASE}/api/ai-agent/scenario`,

  // Scenario CRUD
  createScenario:   (threadId) => `${API_BASE}/api/market-iq/threads/${encodeURIComponent(threadId)}/scenarios`,
  listScenarios:    (threadId) => `${API_BASE}/api/market-iq/threads/${encodeURIComponent(threadId)}/scenarios`,
  getLevers:        (threadId) => `${API_BASE}/api/ai-agent/threads/${encodeURIComponent(threadId)}/levers`,
  updateScenario:   (scenarioId, threadId) => `${API_BASE}/api/market-iq/scenarios/${encodeURIComponent(scenarioId)}?thread_id=${encodeURIComponent(threadId)}`,
  applyScenario:    (scenarioId, threadId) => `${API_BASE}/api/market-iq/scenarios/${encodeURIComponent(scenarioId)}/apply?thread_id=${encodeURIComponent(threadId)}`,
  adoptScenario:    (scenarioId, threadId) => `${API_BASE}/api/market-iq/scenarios/${encodeURIComponent(scenarioId)}/adopt${threadId ? `?thread_id=${encodeURIComponent(threadId)}` : ''}`,
  threadWbs:        (threadId) => `${API_BASE}/api/market-iq/threads/${encodeURIComponent(threadId)}/wbs`,
  deleteAnalysis:   (analysisId) => `${API_BASE}/api/market-iq/analyses/${encodeURIComponent(analysisId)}`,
  // Connector settings and PM sync profile
  connectorStatus: `${API_BASE}/api/connectors/status`,
  connectorUpdate: (connectorId) => `${API_BASE}/api/connectors/${encodeURIComponent(connectorId)}`,
  threadPmSync: (threadId) => `${API_BASE}/api/connectors/threads/${encodeURIComponent(threadId)}/sync`,
  threadJiraSync: (threadId) => `${API_BASE}/api/connectors/threads/${encodeURIComponent(threadId)}/jira/sync`,
};
// ---- Session ID for memory that survives Safari ITP ----
const SID_KEY = 'jas_sid';
function getSid() {
  try {
    let sid = localStorage.getItem(SID_KEY);
    if (!sid) {
      sid = `web-${Math.random().toString(36).slice(2)}-${Date.now()}`;
      localStorage.setItem(SID_KEY, sid);
    }
    return sid;
  } catch {
    return `web-${Date.now()}`;
  }
}

function getToken() {
  return (
    localStorage.getItem('access_token') ||
    localStorage.getItem('token') ||
    null
  );
}

async function _json(resp) {
  const text = await resp.text();
  try { return text ? JSON.parse(text) : {}; } catch { return { raw: text }; }
}

async function _fetch(url, opts = {}) {
  const token = getToken();
  const headers = {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(opts.sidOverride ? { 'X-Session-ID': opts.sidOverride } : opts.withSid ? { 'X-Session-ID': getSid() } : {}),
    ...(opts.headers || {}),
  };
  const resp = await fetch(url, { credentials: 'include', cache: 'no-store', ...opts, headers });
  const data = await _json(resp);
  if (!resp.ok) {
    const msg = data?.error || data?.detail || `HTTP ${resp.status}`;
    const err = new Error(msg);
    err.status = resp.status;
    err.data = data;
    throw err;
  }
  return data;
}

async function postJSON(url, body, { withSid = false, sidOverride } = {}) {
  return _fetch(url, { method: 'POST', body: JSON.stringify(body ?? {}), withSid, sidOverride });
}
async function getJSON(url, { withSid = false, sidOverride } = {}) {
  return _fetch(url, { method: 'GET', withSid, sidOverride });
}
async function putJSON(url, body, { withSid = false, sidOverride } = {}) {
  return _fetch(url, { method: 'PATCH', body: JSON.stringify(body ?? {}), withSid, sidOverride });
}
async function patchJSON(url, body, { withSid = false, sidOverride } = {}) {
  return _fetch(url, { method: 'PATCH', body: JSON.stringify(body ?? {}), withSid, sidOverride });
}
async function upsertJSON(url, body, { withSid = false, sidOverride } = {}) {
  return _fetch(url, { method: 'PUT', body: JSON.stringify(body ?? {}), withSid, sidOverride });
}
async function del(url, { withSid = false, sidOverride } = {}) {
  return _fetch(url, { method: 'DELETE', withSid, sidOverride });
}

function normalizeStart(data) {
  return {
    session_id: data.session_id || data.analysis_id,
    message:    data.reply      || data.message || data.question,
    readiness_score: data.readiness_score ?? 0,
    status: data.status || 'gathering_info',
  };
}

// Shared intake system prompt
const INTAKE_SYSTEM_PROMPT = `
You conduct a natural business discovery chat.
- One concise question at a time.
- Reference what the user already said; no rigid questionnaire.
- Never repeat the same question verbatim; adapt wording if needed.
- Keep it friendly, crisp, and progress toward building a Jaspen scorecard.
`.trim();

export const MarketIQ = {

  // PROMPT ALIGNMENT: `adoptScenario` is handled by this existing `scenario` function.
  // It now correctly returns the result of the `applyScenario` call, which is the adopted snapshot.
  async scenario(payload) {
    const threadId =
      payload?.thread_id ||
      payload?.session_id ||
      payload?.analysis_id;

    if (!threadId) {
      throw new Error('MarketIQ.scenario: thread_id/session_id is required');
    }

    if (payload?.scenario_id) {
      return await postJSON(
        endpoints.applyScenario(payload.scenario_id, threadId),
        {},
        { withSid: true }
      );
    }

    const deltas =
      (payload?.deltas && typeof payload.deltas === 'object')
        ? payload.deltas
        : (payload?.changes && typeof payload.changes === 'object')
          ? payload.changes
          : {};

    const label =
      payload?.label ||
      (typeof payload?.scenario_description === 'string' && payload.scenario_description) ||
      'Custom Scenario';

    const created = await postJSON(
      endpoints.createScenario(threadId),
      {
        deltas,
        label,
        session_id: threadId,
        baseline: payload?.baseline || null,
      },
      { withSid: true }
    );

    const scenarioId =
      created?.scenario_id ||
      created?.scenario?.scenario_id;

    if (!scenarioId) {
      throw new Error('MarketIQ.scenario: failed to create scenario (no scenario_id)');
    }

    // Apply the scenario and return the resulting analysis snapshot
    return await postJSON(
      endpoints.applyScenario(scenarioId, threadId),
      {},
      { withSid: true }
    );
  },

  // ---------- Unified Chat ----------
  async chat({ message, conversation_history, analysis_context, analysis_id }) {
    const data = await postJSON(
      endpoints.chat,
      {
        message,
        conversation_history,
        docType: 'market_iq',
        detailed: true,
        phase: 3,
        systemPrompt:
          'You are a market analyst assisting with deep-dive Q&A on a completed Jaspen analysis. Provide conversational, helpful responses that reference the analysis context when relevant.',
        analysis_context,
        analysis_id,
      },
      { withSid: true }
    );
    return { text: data.response || data.reply || String(data) };
  },

  // ---------- Conversational intake (Claude via /api/chat) ----------
async convoStart({ description, project_id, model_type }) {
    console.log('[MarketIQClient.convoStart] ENTRY', {
      description: description?.substring(0, 50),
      project_id,
    });

    // Default project_id for testing - replace with real project selection later
    const pid = project_id || 'default-jas-project';

    const data = await postJSON(
      endpoints.convoStart,
      {
        message: description,
        project_id: pid,
        name: description.substring(0, 60) || 'New Idea',
        model_type: model_type || undefined,
      },
      { withSid: true }
    );

    console.log('[MarketIQClient.convoStart] RESPONSE', {
      thread_id: data.thread_id,
      session_id: data.session_id,
      readiness: data.readiness,
      has_message: Boolean(data.message || data.reply),
    });

    return {
      session_id: data.thread_id || data.session_id,
      thread_id: data.thread_id || null,
      message: data.message || data.reply,
      readiness: data.readiness || { percent: 0, categories: [] },
      model_type: data.model_type || null,
      status: data.status || 'gathering_info',
    };
  },
async convoContinue({ session_id, user_message, conversation_history, model_type }) {
    console.log('[MarketIQClient.convoContinue] ENTRY', {
      session_id,
      user_message: user_message?.substring(0, 50),
      hasHistory: Boolean(conversation_history?.length),
    });

    const data = await postJSON(
      endpoints.convoNext,
      {
        thread_id: session_id,
        message: user_message,
        model_type: model_type || undefined,
      },
      { withSid: true }
    );

    console.log('[MarketIQClient.convoContinue] RESPONSE', {
      thread_id_sent: session_id,
      response_thread_id: data?.thread_id,
      response_session_id: data?.session_id,
      readiness_in_response: data?.readiness,
      has_message: Boolean(data?.message || data?.reply),
    });

    return {
      ...data,
      message: data.message || data.reply,
      readiness: data.readiness || { percent: 0, categories: [] },
      model_type: data.model_type || null,
    };
  },
async analyzeFromConversation({ session_id, transcript, deterministic = true, seed, project_name, assumptions, model_type }) {
    const data = await postJSON(
      endpoints.analyze,
      {
        thread_id: session_id,
        name: project_name || 'Baseline Analysis',
        framework_id: null, // Uses default "Jaspen Assessment"
        model_type: model_type || undefined,
      },
      { withSid: true, sidOverride: session_id }
    );

    // DEBUG: Log full /analyze response to trace meta.extracted_levers
    console.log('[MarketIQClient.analyzeFromConversation] raw response:', JSON.stringify(data, null, 2));
    console.log('[MarketIQClient.analyzeFromConversation] has meta?', Boolean(data?.analysis?.meta || data?.meta));
    console.log('[MarketIQClient.analyzeFromConversation] extracted_levers?', data?.analysis?.meta?.extracted_levers || data?.meta?.extracted_levers || null);

    return {
      analysis_result: data.analysis || data,
      analysis_id: data.analysis?.id || session_id,
      model_type: data.model_type || null,
    };
  },
    // ---------- Thread bundle (messages + latest analysis + scenarios) ----------
  async fetchBundle(threadId, { msgLimit = 50, scnLimit = 50 } = {}) {
    if (!threadId) throw new Error('MarketIQ.fetchBundle: threadId required');

    const url = endpoints.threadBundle(threadId, msgLimit, scnLimit);
    const token = getToken();

    const res = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        'Content-Type': 'application/json',
        'X-Session-ID': getSid(),
        'Cache-Control': 'no-store',
      },
    });

    if (!res.ok) {
      const txt = await res.text().catch(() => '');
      throw new Error(`${url} -> ${res.status} ${txt}`);
    }
    return res.json();
  },

  // ---------- Streaming ----------
  streamChat({ prompt, onDelta, onDone }) {
    const url = `${API_BASE}/api/chat/stream?q=${encodeURIComponent(prompt )}&sid=${encodeURIComponent(getSid())}`;

    const es = new EventSource(url, { withCredentials: true });

    es.onmessage = (e) => {
      try {
        const { text, error } = JSON.parse(e.data);
        if (error) return console.error(error);
        if (text) onDelta?.(text);
      } catch {}
    };
    es.addEventListener('done', () => { try { es.close(); } finally { onDone?.(); } });
    es.onerror = () =>                 { try { es.close(); } finally { onDone?.(); } };

    return () => { try { es.close(); } catch {} };
  },

  // ===========================
  // ===== NEW helper APIs =====
  // ===========================

  // PROMPT ALIGNMENT: Add beginProject method that sends threadBundleId (sid) and scorecardId
  async beginProject({ threadBundleId, scorecardId, projectName }) {
    return await postJSON(
      endpoints.beginProject,
      {
        sid: threadBundleId,
        scorecard_id: scorecardId,
        project_name: projectName,
        dry_run: false,
        persist: true,
        mode: 'replace',
        commit_message: `begin-project from MarketIQ (scorecard: ${scorecardId})`
      },
      { withSid: true }
    );
  },

  /**
   * Adopt a scenario scorecard as the current scorecard
   */
  async adoptScorecard(threadId, scorecardId) {
    const apiBase = API_BASE;
    const token = getToken();

    const res = await fetch(
      `${apiBase}/api/market-iq/threads/${encodeURIComponent(threadId)}/adopt`,
      {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({ analysis_id: scorecardId }),
      }
    );

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err?.error || `HTTP ${res.status}`);
    }

    return await res.json();
  },

  // Analyses / Scorecards
  listScorecards: async (threadId, { limit = 20, offset = 0 } = {}) =>
    getJSON(`${endpoints.listAnalyses(threadId)}?limit=${limit}&offset=${offset}`, { withSid: true }),

  getScorecard: async (analysis_id) =>
    getJSON(endpoints.deleteAnalysis(analysis_id), { withSid: true }), // Note: deleteAnalysis endpoint seems misnamed if it's for GET

  deleteAnalysis: async (analysis_id) =>
    del(endpoints.deleteAnalysis(analysis_id), { withSid: true }),

  // Scenarios
  createScenario: async (threadId, { deltas = {}, label, session_id, baseline } = {}) =>
    postJSON(endpoints.createScenario(threadId), { deltas, label, session_id: session_id || threadId, baseline: baseline || null }, { withSid: true }),

  listScenarios: async (threadId, { limit = 50, offset = 0 } = {}) =>
    getJSON(`${endpoints.listScenarios(threadId)}?limit=${limit}&offset=${offset}`, { withSid: true }),

  updateScenario: async (scenario_id, { thread_id, deltas = {}, label } = {}) =>
    putJSON(endpoints.updateScenario(scenario_id, thread_id), { deltas, label }, { withSid: true }),

  applyScenario: async (scenario_id, thread_id) =>
    postJSON(endpoints.applyScenario(scenario_id, thread_id), {}, { withSid: true }),

  adoptScenario: async (scenario_id, thread_id) =>
    postJSON(
      endpoints.adoptScenario(scenario_id, thread_id),
      thread_id ? { thread_id } : {},
      { withSid: true }
    ),

  getThreadWbs: async (threadId) =>
    getJSON(endpoints.threadWbs(threadId), { withSid: true }),

  upsertThreadWbs: async (threadId, project_wbs) =>
    putJSON(endpoints.threadWbs(threadId), { project_wbs }, { withSid: true }),
  
  async getLevers(threadId) {
    return getJSON(endpoints.getLevers(threadId));
  },

  // Threads bundle
  getThreadBundle: async (threadId, { msg_limit = 50, scn_limit = 50 } = {}) =>
    getJSON(endpoints.threadBundle(threadId, msg_limit, scn_limit), { withSid: true }),

  // Connector settings
  getConnectorStatus: async () =>
    getJSON(endpoints.connectorStatus, { withSid: true }),

  updateConnectorSettings: async (connectorId, payload = {}) =>
    patchJSON(endpoints.connectorUpdate(connectorId), payload, { withSid: true }),

  getThreadPmSync: async (threadId) =>
    getJSON(endpoints.threadPmSync(threadId), { withSid: true }),

  updateThreadPmSync: async (threadId, payload = {}) =>
    upsertJSON(endpoints.threadPmSync(threadId), payload, { withSid: true }),

  syncThreadWbsToJira: async (threadId) =>
    postJSON(endpoints.threadJiraSync(threadId), {}, { withSid: true }),
};

// Minimal local persistence
const LS_HISTORY = 'jas_history';
const LS_PROJECTS = 'jas_projects';

export const storage = {
  pushHistory(entry) {
    const arr = storage.getHistory();
    const existingIndex = arr.findIndex(item => item.id === entry.id);
    if (existingIndex > -1) {
      arr[existingIndex] = entry;
    } else {
      arr.unshift(entry);
    }
    localStorage.setItem(LS_HISTORY, JSON.stringify(arr.slice(0, 50)));
  },
  getHistory() {
    try { return JSON.parse(localStorage.getItem(LS_HISTORY)) || []; }
    catch { return []; }
  },
  saveProject(project) {
    const arr = storage.getProjects();
    arr.unshift(project);
    localStorage.setItem(LS_PROJECTS, JSON.stringify(arr.slice(0, 100)));
  },
  getProjects() {
    try { return JSON.parse(localStorage.getItem(LS_PROJECTS)) || []; }
    catch { return []; }
  },
};

export { API_BASE };
