// ============================================================================
// File: src/lib/JaspenClient.jsx
// Purpose: Robust client incl. scenarios, unified chat, and stable session SID
//          + NEW endpoints: analyses, scenarios (CRUD), bundle
//          (keeps legacy shapes; falls back where needed)
// ============================================================================

import { API_BASE } from '../../config/apiBase';
import { buildAuthHeaders } from '../../shared/auth/http';

const RETRYABLE_STATUS_CODES = new Set([408, 425, 429, 500, 502, 503, 504]);
const RETRY_BACKOFF_MS = [1000, 2000, 4000];

export const endpoints = {
  // AI Agent endpoints (NEW)
  convoStart:     `${API_BASE}/api/v1/ai-agent/conversation/start`,
  convoNext:      `${API_BASE}/api/v1/ai-agent/conversation/continue`,
  analyze:        `${API_BASE}/api/v1/ai-agent/analyze`,
  readinessSpec:  `${API_BASE}/api/v1/ai-agent/readiness/spec`,
  readinessAudit: (threadId) => `${API_BASE}/api/v1/ai-agent/readiness/audit?thread_id=${encodeURIComponent(threadId)}`,
  
  // Threads
  getThread:      (threadId) => `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(threadId)}`,
  updateThread:   (threadId) => `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(threadId)}`,
  messageFeedback: (threadId, messageIndex) => `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(threadId)}/messages/${encodeURIComponent(messageIndex)}/feedback`,
  regenerate: `${API_BASE}/api/v1/ai-agent/conversation/regenerate`,
  undoMutations: `${API_BASE}/api/v1/ai-agent/conversation/undo-mutations`,
  
  // Analyses
  listAnalyses:   (threadId) => `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(threadId)}/analyses`,
  
  // Legacy chat (keep for now)
  chat:       `${API_BASE}/api/v1/ai-agent/conversation/continue`,
  chatStream: `${API_BASE}/api/v1/chat/stream`,

  // PROMPT ALIGNMENT: Endpoint for beginning a project from a scorecard
  beginProject: `${API_BASE}/api/v1/projects/generate/ai`,
  
  // KEEP OLD ENDPOINTS for backward compat during migration
  threadBundle:   (threadId, msg = 50, scn = 50 ) =>
    `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/bundle?msg_limit=${msg}&scn_limit=${scn}`,
  scenario:   `${API_BASE}/api/v1/ai-agent/scenario`,

  // Scenario CRUD
  createScenario:   (threadId) => `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/scenarios`,
  listScenarios:    (threadId) => `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/scenarios`,
  getLevers:        (threadId) => `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(threadId)}/levers`,
  updateScenario:   (scenarioId, threadId) => `${API_BASE}/api/v1/strategy/scenarios/${encodeURIComponent(scenarioId)}?thread_id=${encodeURIComponent(threadId)}`,
  applyScenario:    (scenarioId, threadId) => `${API_BASE}/api/v1/strategy/scenarios/${encodeURIComponent(scenarioId)}/apply?thread_id=${encodeURIComponent(threadId)}`,
  adoptScenario:    (scenarioId, threadId) => `${API_BASE}/api/v1/strategy/scenarios/${encodeURIComponent(scenarioId)}/adopt${threadId ? `?thread_id=${encodeURIComponent(threadId)}` : ''}`,
  aiScenario:       (threadId) => `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/ai-scenario`,
  aiWbs:            (threadId) => `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/ai-wbs`,
  threadWbs:        (threadId) => `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/wbs`,
  exportScorecardPdf: (threadId, scorecardId = '') =>
    `${API_BASE}/api/v1/export/threads/${encodeURIComponent(threadId)}/scorecard/pdf${scorecardId ? `?scorecard_id=${encodeURIComponent(scorecardId)}` : ''}`,
  exportScorecardPptx: (threadId, scorecardId = '') =>
    `${API_BASE}/api/v1/export/threads/${encodeURIComponent(threadId)}/scorecard/pptx${scorecardId ? `?scorecard_id=${encodeURIComponent(scorecardId)}` : ''}`,
  exportWbsCsv:      (threadId) => `${API_BASE}/api/v1/export/threads/${encodeURIComponent(threadId)}/wbs/csv`,
  exportConversationMarkdown: (threadId) => `${API_BASE}/api/v1/export/threads/${encodeURIComponent(threadId)}/conversation/markdown`,
  exportConversationPdf: (threadId) => `${API_BASE}/api/v1/export/threads/${encodeURIComponent(threadId)}/conversation/pdf`,
  scorecardAssistant: (threadId) => `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/scorecard-assistant`,
  appendMessages:     (threadId) => `${API_BASE}/api/v1/ai-agent/threads/${encodeURIComponent(threadId)}/messages`,
  batchIdeasUpload: `${API_BASE}/api/v1/ai-agent/batch-ideas/upload`,
  batchIdeasById:   (batchId) => `${API_BASE}/api/v1/ai-agent/batch-ideas/${encodeURIComponent(batchId)}`,
  batchIdeasRank:   (batchId) => `${API_BASE}/api/v1/ai-agent/batch-ideas/${encodeURIComponent(batchId)}/rank`,
  batchIdeaClarify: (batchId, ideaId) => `${API_BASE}/api/v1/ai-agent/batch-ideas/${encodeURIComponent(batchId)}/ideas/${encodeURIComponent(ideaId)}/clarify`,
  batchIdeaPromote: (batchId, ideaId) => `${API_BASE}/api/v1/ai-agent/batch-ideas/${encodeURIComponent(batchId)}/ideas/${encodeURIComponent(ideaId)}/promote`,
  batchIdeasPromoteAll: (batchId) => `${API_BASE}/api/v1/ai-agent/batch-ideas/${encodeURIComponent(batchId)}/promote-all`,
  analyzeData:      `${API_BASE}/api/v1/ai-agent/analyze-data`,
  insightsUpload:   `${API_BASE}/api/v1/insights/upload`,
  insightsAnalyze:  `${API_BASE}/api/v1/insights/analyze`,
  insightsDatasets: `${API_BASE}/api/v1/insights/datasets`,
  insightsDeleteDataset: (datasetId) => `${API_BASE}/api/v1/insights/datasets/${encodeURIComponent(datasetId)}`,
  starters:         `${API_BASE}/api/v1/starters`,
  starterById:      (starterId) => `${API_BASE}/api/v1/starters/${encodeURIComponent(starterId)}`,
  deleteAnalysis:   (analysisId) => `${API_BASE}/api/v1/strategy/analyses/${encodeURIComponent(analysisId)}`,
  // Connector settings and PM sync profile
  connectorStatus: `${API_BASE}/api/v1/connectors/status`,
  connectorUpdate: (connectorId) => `${API_BASE}/api/v1/connectors/${encodeURIComponent(connectorId)}`,
  threadPmSync: (threadId) => `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(threadId)}/sync`,
  threadJiraSync: (threadId) => `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(threadId)}/jira/sync`,
  threadWorkfrontSync: (threadId) => `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(threadId)}/workfront/sync`,
  threadSmartsheetSync: (threadId) => `${API_BASE}/api/v1/connectors/threads/${encodeURIComponent(threadId)}/smartsheet/sync`,
  connectorHealth: (connectorId) => `${API_BASE}/api/v1/connectors/${encodeURIComponent(connectorId)}/health`,
  connectorAudit: (connectorId) => `${API_BASE}/api/v1/connectors/${encodeURIComponent(connectorId)}/audit`,
  salesforceOauthStart: `${API_BASE}/api/v1/connectors/salesforce/oauth/start`,
  salesforcePipelineSummary: `${API_BASE}/api/v1/connectors/salesforce/pipeline/summary`,
  snowflakeQuery: `${API_BASE}/api/v1/connectors/snowflake/query`,
  snowflakeKpis: `${API_BASE}/api/v1/connectors/snowflake/kpis`,
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

async function _json(resp) {
  const text = await resp.text();
  try { return text ? JSON.parse(text) : {}; } catch { return { raw: text }; }
}

function sleep(ms) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function formatRetryAfter(seconds) {
  const parsed = Number(seconds);
  if (!Number.isFinite(parsed) || parsed <= 0) return '';
  const rounded = Math.max(1, Math.ceil(parsed));
  if (rounded < 60) return `${rounded} second${rounded === 1 ? '' : 's'}`;
  const minutes = Math.floor(rounded / 60);
  const remainder = rounded % 60;
  if (!remainder) return `${minutes} minute${minutes === 1 ? '' : 's'}`;
  return `${minutes} minute${minutes === 1 ? '' : 's'} ${remainder} second${remainder === 1 ? '' : 's'}`;
}

function buildHttpError(status, data) {
  let msg = data?.message || data?.error || data?.detail || `HTTP ${status}`;
  if (status === 429) {
    const retryHuman = data?.retry_after_human || formatRetryAfter(data?.retry_after_seconds);
    if (retryHuman && !String(msg).includes(retryHuman)) {
      msg = `${msg} Try again in about ${retryHuman}.`;
    }
  }
  const err = new Error(msg);
  err.status = status;
  err.data = data;
  if (status === 429) {
    err.retryAfterSeconds = Number(data?.retry_after_seconds || 0) || null;
    err.retryAfterHuman = data?.retry_after_human || formatRetryAfter(err.retryAfterSeconds);
  }
  return err;
}

function shouldRetryRequest(method, opts = {}, error) {
  const normalized = String(method || 'GET').toUpperCase();
  const retryableRequest = normalized === 'GET' || Boolean(opts.retryable);
  if (!retryableRequest) return false;
  if (!error) return false;
  if (error.name === 'AbortError') return false;
  if (typeof error.status === 'number') {
    return RETRYABLE_STATUS_CODES.has(error.status);
  }
  return true;
}

async function fetchWithRetry(url, fetchOptions, { method = 'GET', retryable = false } = {}) {
  let lastError = null;
  for (let attempt = 0; attempt <= RETRY_BACKOFF_MS.length; attempt += 1) {
    try {
      const resp = await fetch(url, fetchOptions);
      if (!resp.ok) {
        let parsedError = null;
        try {
          await parseErrorResponse(resp);
        } catch (error) {
          parsedError = error;
        }
        if (!shouldRetryRequest(method, { retryable }, parsedError) || attempt >= RETRY_BACKOFF_MS.length) {
          throw parsedError;
        }
        lastError = parsedError;
      } else {
        return resp;
      }
    } catch (error) {
      lastError = error;
      if (!shouldRetryRequest(method, { retryable }, error) || attempt >= RETRY_BACKOFF_MS.length) {
        throw error;
      }
    }
    await sleep(RETRY_BACKOFF_MS[attempt]);
  }
  throw lastError || new Error('Request failed');
}

async function _fetch(url, opts = {}) {
  const method = String(opts.method || 'GET').toUpperCase();
  const headers = {
    ...buildAuthHeaders({ 'Content-Type': 'application/json' }, method),
    ...(opts.sidOverride ? { 'X-Session-ID': opts.sidOverride } : opts.withSid ? { 'X-Session-ID': getSid() } : {}),
    ...(opts.headers || {}),
  };
  let lastError = null;
  for (let attempt = 0; attempt <= RETRY_BACKOFF_MS.length; attempt += 1) {
    try {
      const resp = await fetch(url, { credentials: 'include', cache: 'no-store', ...opts, headers });
      const data = await _json(resp);
      if (!resp.ok) {
        throw buildHttpError(resp.status, data);
      }
      return data;
    } catch (error) {
      lastError = error;
      if (!shouldRetryRequest(method, opts, error) || attempt >= RETRY_BACKOFF_MS.length) {
        throw error;
      }
      await sleep(RETRY_BACKOFF_MS[attempt]);
    }
  }
  throw lastError || new Error('Request failed');
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

async function parseErrorResponse(resp) {
  const text = await resp.text().catch(() => '');
  try {
    const data = text ? JSON.parse(text) : {};
    if (resp.status === 429) {
      const retryAfterHeader = resp.headers.get('Retry-After');
      const retryAfterSeconds = Number(data?.retry_after_seconds || retryAfterHeader || 0) || null;
      if (retryAfterSeconds && !data?.retry_after_seconds) data.retry_after_seconds = retryAfterSeconds;
      if (!data?.retry_after_human && retryAfterSeconds) data.retry_after_human = formatRetryAfter(retryAfterSeconds);
    }
    throw buildHttpError(resp.status, data);
  } catch (parseError) {
    if (parseError?.status) throw parseError;
    const err = new Error(text || `HTTP ${resp.status}`);
    err.status = resp.status;
    err.data = { raw: text };
    if (resp.status === 429) {
      const retryAfterHeader = resp.headers.get('Retry-After');
      const retryAfterSeconds = Number(retryAfterHeader || 0) || null;
      err.retryAfterSeconds = retryAfterSeconds;
      err.retryAfterHuman = formatRetryAfter(retryAfterSeconds);
      if (err.retryAfterHuman) {
        err.message = `You've hit a temporary request limit. Please try again in about ${err.retryAfterHuman}. If you need higher throughput, you can upgrade your plan or add credits from Account.`;
      }
    }
    throw err;
  }
}

async function downloadBinary(url) {
  const resp = await fetchWithRetry(url, {
    method: 'GET',
    credentials: 'include',
    cache: 'no-store',
    headers: buildAuthHeaders({}, 'GET'),
  }, { method: 'GET' });

  const blob = await resp.blob();
  const disposition = resp.headers.get('content-disposition') || '';
  const match =
    disposition.match(/filename\*=UTF-8''([^;]+)/i) ||
    disposition.match(/filename="?([^"]+)"?/i);
  const filename = match?.[1] ? decodeURIComponent(match[1]) : null;
  return { blob, filename, contentType: resp.headers.get('content-type') || '' };
}

async function postForm(url, form, { withSid = false, sidOverride, retryable = false } = {}) {
  const headers = {
    ...buildAuthHeaders({}, 'POST'),
    ...(sidOverride ? { 'X-Session-ID': sidOverride } : withSid ? { 'X-Session-ID': getSid() } : {}),
  };
  const resp = await fetchWithRetry(url, {
    method: 'POST',
    credentials: 'include',
    cache: 'no-store',
    headers,
    body: form,
  }, { method: 'POST', retryable });
  return _json(resp);
}

function buildConversationForm(fields = {}, files = []) {
  const form = new FormData();
  Object.entries(fields || {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (typeof value === 'object') {
      form.append(key, JSON.stringify(value));
      return;
    }
    form.append(key, String(value));
  });
  (Array.isArray(files) ? files : []).forEach((file) => {
    if (file instanceof File) form.append('files', file);
  });
  return form;
}

async function openRetriedStream(url, { body, sid, isForm = false } = {}) {
  const baseHeaders = isForm
    ? buildAuthHeaders({ Accept: 'text/event-stream' }, 'POST')
    : buildAuthHeaders({
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    }, 'POST');
  return fetchWithRetry(url, {
    method: 'POST',
    credentials: 'include',
    cache: 'no-store',
    headers: {
      ...baseHeaders,
      'X-Session-ID': sid || getSid(),
    },
    body,
  }, { method: 'POST', retryable: true });
}

function parseSseChunk(chunk) {
  const lines = String(chunk || '').split('\n');
  const dataLines = [];
  for (const line of lines) {
    if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart());
    }
  }
  if (!dataLines.length) return null;
  try {
    return JSON.parse(dataLines.join('\n'));
  } catch {
    return null;
  }
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

export const Jaspen = {

  // PROMPT ALIGNMENT: `adoptScenario` is handled by this existing `scenario` function.
  // It now correctly returns the result of the `applyScenario` call, which is the adopted snapshot.
  async scenario(payload) {
    const threadId =
      payload?.thread_id ||
      payload?.session_id ||
      payload?.analysis_id;

    if (!threadId) {
      throw new Error('Jaspen.scenario: thread_id/session_id is required');
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
      throw new Error('Jaspen.scenario: failed to create scenario (no scenario_id)');
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
        docType: 'strategy',
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

  // ---------- Conversational intake (Claude via /api/v1/chat) ----------
async convoStart({ description, project_id, model_type, strategy_objective, intake_context, lever_defaults, starter_id, attachments }) {
    console.log('[JaspenClient.convoStart] ENTRY', {
      description: description?.substring(0, 50),
      project_id,
    });

    // Default project_id for testing - replace with real project selection later
    const pid = project_id || 'default-jas-project';

    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;
    const data = hasAttachments
      ? await postForm(
        endpoints.convoStart,
        buildConversationForm({
          message: description,
          project_id: pid,
          name: description.substring(0, 60) || 'New Idea',
          model_type: model_type || undefined,
          strategy_objective: strategy_objective || undefined,
          intake_context: intake_context && typeof intake_context === 'object' ? intake_context : undefined,
          lever_defaults: lever_defaults && typeof lever_defaults === 'object' ? lever_defaults : undefined,
          starter_id: starter_id || undefined,
        }, attachments),
        { withSid: true, retryable: true }
      )
      : await postJSON(
        endpoints.convoStart,
        {
          message: description,
          project_id: pid,
          name: description.substring(0, 60) || 'New Idea',
          model_type: model_type || undefined,
          strategy_objective: strategy_objective || undefined,
          intake_context: intake_context && typeof intake_context === 'object' ? intake_context : undefined,
          lever_defaults: lever_defaults && typeof lever_defaults === 'object' ? lever_defaults : undefined,
          starter_id: starter_id || undefined,
        },
        { withSid: true }
      );

    console.log('[JaspenClient.convoStart] RESPONSE', {
      thread_id: data.thread_id,
      session_id: data.session_id,
      readiness: data.readiness,
      has_message: Boolean(data.message || data.reply),
    });

    return {
      session_id: data.thread_id || data.session_id,
      thread_id: data.thread_id || null,
      message: data.message || data.reply,
      assistant_message_index: data.assistant_message_index,
      readiness: data.readiness || { percent: 0, categories: [] },
      model_type: data.model_type || null,
      strategy_objective: data.strategy_objective || null,
      intake_context: data.intake_context || null,
      status: data.status || 'gathering_info',
    };
  },
async convoContinue({ session_id, user_message, conversation_history, model_type, strategy_objective, attachments }) {
    console.log('[JaspenClient.convoContinue] ENTRY', {
      session_id,
      user_message: user_message?.substring(0, 50),
      hasHistory: Boolean(conversation_history?.length),
    });

    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;
    const data = hasAttachments
      ? await postForm(
        endpoints.convoNext,
        buildConversationForm({
          thread_id: session_id,
          message: user_message,
          model_type: model_type || undefined,
          strategy_objective: strategy_objective || undefined,
        }, attachments),
        { withSid: true, retryable: true }
      )
      : await postJSON(
        endpoints.convoNext,
        {
          thread_id: session_id,
          message: user_message,
          model_type: model_type || undefined,
          strategy_objective: strategy_objective || undefined,
        },
        { withSid: true }
      );

    console.log('[JaspenClient.convoContinue] RESPONSE', {
      thread_id_sent: session_id,
      response_thread_id: data?.thread_id,
      response_session_id: data?.session_id,
      readiness_in_response: data?.readiness,
      has_message: Boolean(data?.message || data?.reply),
    });

    return {
      ...data,
      message: data.message || data.reply,
      assistant_message_index: data.assistant_message_index,
      readiness: data.readiness || { percent: 0, categories: [] },
      model_type: data.model_type || null,
      strategy_objective: data.strategy_objective || null,
    };
  },
  async streamConversationStart({
    description,
    project_id,
    model_type,
    strategy_objective,
    intake_context,
    lever_defaults,
    starter_id,
    attachments,
    onDelta,
    onToolUse,
    onToolResult,
    onDone,
  }) {
    const url = `${endpoints.convoStart}?stream=true`;
    const pid = project_id || 'default-jas-project';
    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;
    const body = hasAttachments
      ? buildConversationForm({
        message: description,
        project_id: pid,
        name: description.substring(0, 60) || 'New Idea',
        model_type: model_type || undefined,
        strategy_objective: strategy_objective || undefined,
        intake_context: intake_context && typeof intake_context === 'object' ? intake_context : undefined,
        lever_defaults: lever_defaults && typeof lever_defaults === 'object' ? lever_defaults : undefined,
        starter_id: starter_id || undefined,
      }, attachments)
      : JSON.stringify({
        message: description,
        project_id: pid,
        name: description.substring(0, 60) || 'New Idea',
        model_type: model_type || undefined,
        strategy_objective: strategy_objective || undefined,
        intake_context: intake_context && typeof intake_context === 'object' ? intake_context : undefined,
        lever_defaults: lever_defaults && typeof lever_defaults === 'object' ? lever_defaults : undefined,
        starter_id: starter_id || undefined,
      });
    const resp = await openRetriedStream(url, {
      sid: getSid(),
      body,
      isForm: hasAttachments,
    });

    const reader = resp.body?.getReader();
    if (!reader) {
      throw new Error('Streaming not supported by this browser.');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let donePayload = null;

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const rawChunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const payload = parseSseChunk(rawChunk);
        if (payload) {
          if (payload.type === 'delta' && payload.text) onDelta?.(payload.text);
          else if (payload.type === 'tool_use') onToolUse?.(payload);
          else if (payload.type === 'tool_result') onToolResult?.(payload);
          else if (payload.type === 'done') {
            donePayload = payload;
            onDone?.(payload);
          } else if (payload.type === 'error') {
            const err = new Error(payload.error || 'Streaming request failed');
            err.data = payload;
            throw err;
          }
        }
        boundary = buffer.indexOf('\n\n');
      }

      if (done) break;
    }

    if (!donePayload) {
      throw new Error('Streaming response ended without a done event.');
    }
    return donePayload;
  },
  async streamConversation({
    session_id,
    user_message,
    model_type,
    strategy_objective,
    attachments,
    onDelta,
    onToolUse,
    onToolResult,
    onDone,
  }) {
    const url = `${endpoints.convoNext}?stream=true`;
    const hasAttachments = Array.isArray(attachments) && attachments.length > 0;
    const body = hasAttachments
      ? buildConversationForm({
        thread_id: session_id,
        message: user_message,
        model_type: model_type || undefined,
        strategy_objective: strategy_objective || undefined,
      }, attachments)
      : JSON.stringify({
        thread_id: session_id,
        message: user_message,
        model_type: model_type || undefined,
        strategy_objective: strategy_objective || undefined,
      });
    const resp = await openRetriedStream(url, {
      sid: getSid(),
      body,
      isForm: hasAttachments,
    });

    const reader = resp.body?.getReader();
    if (!reader) {
      throw new Error('Streaming not supported by this browser.');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let donePayload = null;

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const rawChunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const payload = parseSseChunk(rawChunk);
        if (payload) {
          if (payload.type === 'delta' && payload.text) onDelta?.(payload.text);
          else if (payload.type === 'tool_use') onToolUse?.(payload);
          else if (payload.type === 'tool_result') onToolResult?.(payload);
          else if (payload.type === 'done') {
            donePayload = payload;
            onDone?.(payload);
          } else if (payload.type === 'error') {
            const err = new Error(payload.error || 'Streaming request failed');
            err.data = payload;
            throw err;
          }
        }
        boundary = buffer.indexOf('\n\n');
      }

      if (done) break;
    }

    if (!donePayload) {
      throw new Error('Streaming response ended without a done event.');
    }
    return donePayload;
  },
  async streamRegenerate({
    session_id,
    model_type,
    onDelta,
    onToolUse,
    onToolResult,
    onDone,
  }) {
    const url = `${endpoints.regenerate}?stream=true`;
    const resp = await openRetriedStream(url, {
      sid: getSid(),
      body: JSON.stringify({
        thread_id: session_id,
        model_type: model_type || undefined,
      }),
    });

    const reader = resp.body?.getReader();
    if (!reader) {
      throw new Error('Streaming not supported by this browser.');
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let donePayload = null;

    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done });

      let boundary = buffer.indexOf('\n\n');
      while (boundary >= 0) {
        const rawChunk = buffer.slice(0, boundary);
        buffer = buffer.slice(boundary + 2);
        const payload = parseSseChunk(rawChunk);
        if (payload) {
          if (payload.type === 'delta' && payload.text) onDelta?.(payload.text);
          else if (payload.type === 'tool_use') onToolUse?.(payload);
          else if (payload.type === 'tool_result') onToolResult?.(payload);
          else if (payload.type === 'done') {
            donePayload = payload;
            onDone?.(payload);
          } else if (payload.type === 'error') {
            const err = new Error(payload.error || 'Regenerate stream error');
            err.data = payload;
            throw err;
          }
        }
        boundary = buffer.indexOf('\n\n');
      }

      if (done) break;
    }

    if (!donePayload) {
      throw new Error('Regenerate stream ended without a done event.');
    }
    return donePayload;
  },
  async messageFeedback(threadId, messageIndex, value) {
    return postJSON(
      endpoints.messageFeedback(threadId, messageIndex),
      { value },
      { withSid: true }
    );
  },
  async undoMutations(threadId) {
    return postJSON(
      endpoints.undoMutations,
      { thread_id: threadId },
      { withSid: true }
    );
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
    console.log('[JaspenClient.analyzeFromConversation] raw response:', JSON.stringify(data, null, 2));
    console.log('[JaspenClient.analyzeFromConversation] has meta?', Boolean(data?.analysis?.meta || data?.meta));
    console.log('[JaspenClient.analyzeFromConversation] extracted_levers?', data?.analysis?.meta?.extracted_levers || data?.meta?.extracted_levers || null);

    return {
      analysis_result: data.analysis || data,
      analysis_id: data.analysis?.id || session_id,
      model_type: data.model_type || null,
    };
  },
    // ---------- Thread bundle (messages + latest analysis + scenarios) ----------
  async fetchBundle(threadId, { msgLimit = 50, scnLimit = 50 } = {}) {
    if (!threadId) throw new Error('Jaspen.fetchBundle: threadId required');

    const url = endpoints.threadBundle(threadId, msgLimit, scnLimit);

    const res = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: {
        ...buildAuthHeaders({}, 'GET'),
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
    const url = `${API_BASE}/api/v1/chat/stream?q=${encodeURIComponent(prompt )}&sid=${encodeURIComponent(getSid())}`;

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
        commit_message: `begin-project from Jaspen (scorecard: ${scorecardId})`
      },
      { withSid: true }
    );
  },

  /**
   * Adopt a scenario scorecard as the current scorecard
   */
  async adoptScorecard(threadId, scorecardId) {
    return _fetch(
      `${API_BASE}/api/v1/strategy/threads/${encodeURIComponent(threadId)}/adopt`,
      {
        method: 'POST',
        retryable: true,
        body: JSON.stringify({ analysis_id: scorecardId }),
      }
    );
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
    _fetch(endpoints.applyScenario(scenario_id, thread_id), {
      method: 'POST',
      body: JSON.stringify({}),
      withSid: true,
      retryable: true,
    }),

  adoptScenario: async (scenario_id, thread_id) =>
    _fetch(
      endpoints.adoptScenario(scenario_id, thread_id),
      {
        method: 'POST',
        body: JSON.stringify(thread_id ? { thread_id } : {}),
        withSid: true,
        retryable: true,
      }
    ),

  generateAiScenario: async (threadId, promptOrPayload = '') => {
    const payload = (promptOrPayload && typeof promptOrPayload === 'object')
      ? promptOrPayload
      : { prompt: String(promptOrPayload || '').trim() };
    return postJSON(endpoints.aiScenario(threadId), payload, { withSid: true });
  },

  setThreadObjective: async (threadId, strategy_objective, objective_explicitly_set = true) =>
    patchJSON(
      endpoints.updateThread(threadId),
      { strategy_objective, objective_explicitly_set },
      { withSid: true }
    ),

  generateAiWbs: async (threadId, scenarioIdOrPayload = null) => {
    const payload = (scenarioIdOrPayload && typeof scenarioIdOrPayload === 'object')
      ? scenarioIdOrPayload
      : { scenario_id: scenarioIdOrPayload || null };
    return postJSON(endpoints.aiWbs(threadId), payload, { withSid: true });
  },

  getThreadWbs: async (threadId) =>
    getJSON(endpoints.threadWbs(threadId), { withSid: true }),

  upsertThreadWbs: async (threadId, project_wbs) =>
    putJSON(endpoints.threadWbs(threadId), { project_wbs }, { withSid: true }),

  downloadScorecardPdf: async (threadId, { scorecardId } = {}) => {
    if (!threadId) throw new Error('threadId is required');
    return downloadBinary(endpoints.exportScorecardPdf(threadId, scorecardId || ''));
  },

  downloadScorecardPptx: async (threadId, { scorecardId } = {}) => {
    if (!threadId) throw new Error('threadId is required');
    return downloadBinary(endpoints.exportScorecardPptx(threadId, scorecardId || ''));
  },

  downloadWbsCsv: async (threadId) => {
    if (!threadId) throw new Error('threadId is required');
    return downloadBinary(endpoints.exportWbsCsv(threadId));
  },

  downloadConversationMarkdown: async (threadId) => {
    if (!threadId) throw new Error('threadId is required');
    return downloadBinary(endpoints.exportConversationMarkdown(threadId));
  },

  downloadConversationPdf: async (threadId) => {
    if (!threadId) throw new Error('threadId is required');
    return downloadBinary(endpoints.exportConversationPdf(threadId));
  },

  analyzeDataFile: async ({ file, thread_id, prompt } = {}) => {
    if (!file) throw new Error('file is required');
    const form = new FormData();
    form.append('file', file);
    if (thread_id) form.append('thread_id', thread_id);
    if (prompt) form.append('prompt', prompt);
    return postForm(endpoints.analyzeData, form, { withSid: true, retryable: true });
  },

  uploadBatchIdeas: async (file) => {
    if (!file) throw new Error('file is required');
    const form = new FormData();
    form.append('file', file);
    return postForm(endpoints.batchIdeasUpload, form, { withSid: true, retryable: true });
  },

  getBatchIdeas: async (batchId) =>
    getJSON(endpoints.batchIdeasById(batchId), { withSid: true }),

  rankBatchIdeas: async (batchId, payload = {}) =>
    postJSON(endpoints.batchIdeasRank(batchId), payload, { withSid: true }),

  clarifyIdea: async (batchId, ideaId, answers) =>
    postJSON(endpoints.batchIdeaClarify(batchId, ideaId), { answers }, { withSid: true }),

  promoteIdea: async (batchId, ideaId, payload = {}) =>
    postJSON(endpoints.batchIdeaPromote(batchId, ideaId), payload, { withSid: true }),

  promoteAllIdeas: async (batchId, payload = {}) =>
    postJSON(endpoints.batchIdeasPromoteAll(batchId), payload, { withSid: true }),

  uploadInsightsDataset: async (file) => {
    if (!file) throw new Error('file is required');
    const form = new FormData();
    form.append('file', file);
    return postForm(endpoints.insightsUpload, form, { withSid: true, retryable: true });
  },

  listInsightsDatasets: async () =>
    getJSON(endpoints.insightsDatasets, { withSid: true }),

  analyzeInsightsDataset: async ({ dataset_id, question = '' } = {}) =>
    postJSON(
      endpoints.insightsAnalyze,
      { dataset_id, question: String(question || '').trim() },
      { withSid: true }
    ),

  deleteInsightsDataset: async (datasetId) =>
    del(endpoints.insightsDeleteDataset(datasetId), { withSid: true }),

  listStarters: async () =>
    getJSON(endpoints.starters, { withSid: true }),

  createStarter: async ({ thread_id, name, description = '', is_shared = false } = {}) =>
    postJSON(
      endpoints.starters,
      {
        thread_id,
        name,
        description: String(description || '').trim() || undefined,
        is_shared: Boolean(is_shared),
      },
      { withSid: true }
    ),

  updateStarter: async (starterId, payload = {}) =>
    patchJSON(endpoints.starterById(starterId), payload, { withSid: true }),

  deleteStarter: async (starterId) =>
    del(endpoints.starterById(starterId), { withSid: true }),
  
  async getLevers(threadId) {
    return getJSON(endpoints.getLevers(threadId));
  },

  // Threads bundle
  getThreadBundle: async (threadId, { msg_limit = 50, scn_limit = 50 } = {}) =>
    getJSON(endpoints.threadBundle(threadId, msg_limit, scn_limit), { withSid: true }),

  scorecardAssistant: async (threadId, payload = {}) =>
    postJSON(endpoints.scorecardAssistant(threadId), payload, { withSid: true }),

  appendMessages: async (threadId, messages = []) =>
    postJSON(endpoints.appendMessages(threadId), { messages }, { withSid: true }),

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

  syncThreadWbsToWorkfront: async (threadId) =>
    postJSON(endpoints.threadWorkfrontSync(threadId), {}, { withSid: true }),

  syncThreadWbsToSmartsheet: async (threadId) =>
    postJSON(endpoints.threadSmartsheetSync(threadId), {}, { withSid: true }),
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
