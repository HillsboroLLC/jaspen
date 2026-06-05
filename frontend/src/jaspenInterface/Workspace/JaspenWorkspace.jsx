// ============================================================================
// File: frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx
// Purpose: Canvas-style editor for a single artifact (scorecard or trade-off).
//          Opens in its own browser tab via /workspace/:threadId/:scorecardId.
//          Layout: left sidebar = Jaspen chat (scoped to this artifact);
//          center = canvas with renderScorecardCard + inline editable text;
//          footer = Download PDF / Share / Reset to original.
//
//          v1 / BETA scope: cosmetic edits only (title, headings, narrative,
//          accent color). Analytical fields (scores, risks, recommendations)
//          stay read-only — a rescore is a separate conversation.
// ============================================================================

import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams, useNavigate, useSearchParams } from 'react-router-dom';
import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import { faArrowLeft, faDownload, faShare, faRotateLeft, faPaperPlane, faDiagramProject, faSpinner } from '@fortawesome/free-solid-svg-icons';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

import { Jaspen } from './JaspenClient';
import { authFetch } from '../../shared/auth/http';
import { API_BASE } from '../../config/apiBase';
import TradeoffView from './TradeoffView';
import ChoicePrompt, { parseChoicePrompt } from './ChoicePrompt';
import GridLayout, { WidthProvider } from 'react-grid-layout';
import 'react-grid-layout/css/styles.css';
import 'react-resizable/css/styles.css';
import JaspenExecutionCanvas from './JaspenExecutionCanvas';

// Custom scorecard blocks live on a true 12-col grid: drag the handle to move,
// drag the corner to resize to ANY size (not 4 fixed widths). WidthProvider makes
// the grid fill the scorecard card width.
const BlockGrid = WidthProvider(GridLayout);

// Sentinel scorecardId values that route the canvas to a non-scorecard
// artifact view. Keep these in sync with the entry-point links in
// JaspenChat's Session Artifacts dropdown.
const SENTINEL_TRADEOFF = '__tradeoff__';
const SENTINEL_EXECUTION = '__execution__';

// Color palette matched against the chat scorecard's renderScorecardCard.
const COLOR_NAVY = '#0f172a';
const COLOR_ROSE = '#a0036c';
const COLOR_RISK_ORANGE = '#f59e0b';

// Generic placeholders that should never surface as an idea name.
const _GENERIC_TITLES = new Set([
  'baseline analysis', 'baseline', 'jaspen project', 'jaspen analysis',
  'strategy analysis', 'initiative', 'untitled', 'untitled idea',
  'untitled scorecard', 'project',
]);
const _GENERIC_TITLE_PATTERNS = [/^version\s+\d+$/i, /^v\d+$/i, /^scenario\s+[a-z]$/i];

// Default section config for the scorecard canvas section-grid. Defined as a
// module-level const (not state) so it is stable across renders.
// cols is out of 4 — the outer grid uses repeat(4, 1fr)
// 1 = 25%  2 = 50%  3 = 75%  4 = 100%
const DEFAULT_SCORECARD_SECTIONS = [
  { key: 'score',      label: 'Score',                cols: 4, locked: true,  x: 0, y: 0,  w: 12, h: 4 },
  { key: 'executive',  label: 'Executive Summary',    cols: 4, locked: false, x: 0, y: 4,  w: 12, h: 5 },
  { key: 'dimensions', label: 'Dimensions',           cols: 4, locked: true,  dimCols: 2, dimOrder: null, x: 0, y: 9, w: 12, h: 8 },
  { key: 'risks',      label: 'Top Risks',            cols: 2, locked: false, x: 0, y: 17, w: 6,  h: 6 },
  { key: 'scenario',   label: 'Recommended Scenario', cols: 2, locked: true,  x: 6, y: 17, w: 6,  h: 6 },
];

function _pickMeaningful(...candidates) {
  for (const c of candidates) {
    const v = String(c || '').trim();
    if (!v) continue;
    if (_GENERIC_TITLES.has(v.toLowerCase())) continue;
    if (_GENERIC_TITLE_PATTERNS.some((re) => re.test(v))) continue;
    return v;
  }
  return null;
}

// Derive a short idea name (≤7 words, natural-break aware) from a chat message.
function _deriveFromMessage(text) {
  if (!text) return null;
  let raw = String(text).trim();
  if (!raw) return null;
  raw = raw.replace(
    /^(goal\s*[:–-]\s*|my goal\s+(is\s+)?[:–-]?\s*|i want to\s+|we want to\s+|we('re| are) (building|launching|creating)\s+|idea\s*[:–-]\s*|let'?s\s+(pivot\s+to\s+|add\s+|change\s+to\s+)|what\s+if\s+we\s+|please\s+score\s+(this|that)?\s*)/i,
    '',
  );
  const firstSentence = raw.split(/[.!?\n]/)[0].trim();
  const cleaned = firstSentence.length > 0 ? firstSentence : raw;
  const words = cleaned.split(/\s+/);
  if (words.length <= 7) return cleaned;
  const BREAKS = new Set(['for', 'to', 'that', 'which', 'and', 'or', 'with', 'in', 'on', 'at', 'by', 'from', 'via', 'using', 'through', 'across', 'into', 'of', 'about', 'between']);
  for (let i = Math.min(6, words.length - 1); i >= 3; i--) {
    if (BREAKS.has(words[i].toLowerCase().replace(/[^a-z]/g, ''))) {
      return words.slice(0, i).join(' ');
    }
  }
  return words.slice(0, 7).join(' ');
}

/**
 * Apply display_overrides on top of a raw scorecard payload. Overrides are
 * purely cosmetic — anything missing falls through to the original value.
 * Generic placeholder names (Baseline Analysis, etc.) are stripped so the
 * canvas always shows a real idea name.
 */
function applyOverrides(scorecard, overrides) {
  if (!scorecard) return null;
  const ov = overrides && typeof overrides === 'object' ? overrides : {};
  const meaningfulName = _pickMeaningful(
    ov.title,
    scorecard.name,
    scorecard.project_name,
    scorecard.title,
    scorecard.initiative_name,
  ) || 'Untitled idea';
  return {
    ...scorecard,
    project_name: meaningfulName,
    executive_summary: ov.executive_summary ?? scorecard.executive_summary,
    // Risks + recommended scenario are qualitative narrative — they don't feed
    // the numeric score, so they're manually editable (cosmetic override wins).
    top_risks: ov.top_risks ?? scorecard.top_risks,
    recommended_scenario: ov.recommended_scenario ?? scorecard.recommended_scenario,
    _accent_color: ov.accent_color ?? scorecard._accent_color ?? null,
    _display_overrides: ov,
  };
}

// Chat-driven execution-plan creation. Returns true when the user's message
// should trigger an inline plan build instead of a normal chat reply. Two
// paths:
//   1. A direct ask — "build an execution plan", "create the WBS", etc.
//   2. An affirmative ("yes", "do it", "go ahead") *immediately after* the AI
//      offered to build one (we sniff the previous assistant turn for the
//      offer so a bare "yes" in another context doesn't hijack the chat).
const _EXEC_PLAN_NOUN = /(execution plan|exec plan|work breakdown|\bwbs\b|project plan|action plan|implementation plan|delivery plan|roll[- ]?out plan)/i;
const _EXEC_PLAN_VERB = /\b(build|create|generate|make|draft|put together|spin up|give me|map out|lay out|outline|produce|develop)\b/i;
const _AFFIRMATIVE = /^(yes|yep|yeah|yup|sure|ok|okay|please|please do|do it|go ahead|sounds good|let'?s do it|let'?s go|build it|create it|generate it|make it|that works|go for it|absolutely|definitely)\b/i;
function _detectExecPlanIntent(userText, lastAiText) {
  const t = String(userText || '').trim();
  if (!t) return false;
  // Direct ask: a build verb + an execution-plan noun in the same message.
  if (_EXEC_PLAN_VERB.test(t) && _EXEC_PLAN_NOUN.test(t)) return true;
  // Affirmative right after the AI offered a plan.
  if (_AFFIRMATIVE.test(t) && _EXEC_PLAN_NOUN.test(String(lastAiText || ''))) return true;
  return false;
}

// Workspace chat persists per artifact (thread + scorecard/sentinel) in
// localStorage so a hard refresh keeps the conversation. We never persist the
// transient "pending" placeholder turns.
function _chatStorageKey(threadId, scorecardId) {
  return `jw-chat-${threadId}-${scorecardId}`;
}
function _readWorkspaceChat(key) {
  try {
    const saved = localStorage.getItem(key);
    if (!saved) return [];
    const parsed = JSON.parse(saved);
    return Array.isArray(parsed) ? parsed.filter((m) => m && !m.pending) : [];
  } catch { return []; }
}
function _writeWorkspaceChat(key, history) {
  try {
    const durable = (Array.isArray(history) ? history : []).filter((m) => m && !m.pending);
    if (durable.length === 0) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(durable));
  } catch { /* quota / disabled storage — non-fatal */ }
}

// Map the thread's persisted main-conversation messages into the {role,content}
// shape the agent expects. This is the "context that got the user here" — we
// hand the agent the originating conversation so a freshly-loaded workspace
// chat still reasons from the same history the main thread had.
function _originContextFromBundle(bundle, { limit = 24, maxLen = 4000 } = {}) {
  const msgs = Array.isArray(bundle?.messages) ? bundle.messages : [];
  return msgs
    .map((m) => ({
      role: (m?.role === 'user' || m?.sender === 'user') ? 'user' : 'assistant',
      content: String(m?.content ?? m?.text ?? '').trim().slice(0, maxLen),
    }))
    .filter((m) => m.content)
    .slice(-limit);
}

export default function JaspenWorkspace() {
  const { threadId, scorecardId } = useParams();
  const navigate = useNavigate();

  // View kind + which idea's execution plan is open. Every idea (scorecard)
  // has its OWN execution plan, so the execution canvas is scoped by
  // ?idea=<scorecardId>. On a scorecard view the "active idea" is the scorecard
  // itself; on the execution canvas it comes from the query string. `artifactId`
  // keys both the per-idea execution chat and the plan storage so ideas never
  // bleed into each other.
  const isTradeoff = scorecardId === SENTINEL_TRADEOFF;
  const isExecution = scorecardId === SENTINEL_EXECUTION;
  const isScorecard = !isTradeoff && !isExecution;
  const [searchParams] = useSearchParams();
  const ideaParam = searchParams.get('idea') || null;
  const execIdeaId = isExecution ? ideaParam : (isScorecard ? scorecardId : null);
  const artifactId = isExecution && ideaParam
    ? `${SENTINEL_EXECUTION}::${ideaParam}`
    : scorecardId;
  const [bundle, setBundle] = useState(null);
  // When the execution plan is opened via the legacy `__execution__` route
  // (no ?idea= in the URL), the server still tells us which idea this plan
  // belongs to via the WBS response's scorecard_id. Capture it so the header
  // can name the idea instead of showing a bare "Execution plan".
  const [resolvedExecScorecardId, setResolvedExecScorecardId] = useState(null);
  const [bundleError, setBundleError] = useState(null);
  const [snapshot, setSnapshot] = useState(null);
  const [overrides, setOverrides] = useState({});
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState(null);
  const [error, setError] = useState(null);
  const [chatInput, setChatInput] = useState('');
  const [exportMenuOpen, setExportMenuOpen] = useState(false);
  const [linkCopied, setLinkCopied] = useState(false);
  // Element picker for "+ Add block": choose a block TYPE (text / callout / quote).
  const [addBlockMenuOpen, setAddBlockMenuOpen] = useState(false);
  // Two-step delete confirm for custom blocks (the × shouldn't nuke a section in one click).
  const [confirmDeleteBlockId, setConfirmDeleteBlockId] = useState(null);
  // "Saved just now" flash for the force-save button.
  const [savedFlash, setSavedFlash] = useState(false);
  // Per-artifact storage key. The chat is seeded synchronously from localStorage
  // on first render (no empty flash) and re-loaded whenever the artifact key
  // changes (e.g. navigating scorecard → execution in the same mounted view).
  const chatKey = _chatStorageKey(threadId, artifactId);
  const [chatHistory, setChatHistory] = useState(() => _readWorkspaceChat(chatKey));
  const firstChatLoadRef = useRef(true);
  const skipChatSaveRef = useRef(false);
  const chatSaveTimerRef = useRef(null);
  const chatScrollRef = useRef(null);
  // Auto-grow the workspace composer as the user types (and reset after send).
  const chatComposerRef = useRef(null);
  useEffect(() => {
    const el = chatComposerRef.current;
    if (el) { el.style.height = 'auto'; el.style.height = `${Math.min(el.scrollHeight, 140)}px`; }
  }, [chatInput]);
  const [chatBusy, setChatBusy] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const saveTimerRef = useRef(null);
  const skipNextSaveRef = useRef(true); // first render = freshly loaded, don't save back
  const [sectionLayout, setSectionLayout] = useState(() => {
    try {
      const saved = localStorage.getItem(`jw-layout-${threadId}-${scorecardId}`);
      if (saved) {
        const parsed = JSON.parse(saved);
        return DEFAULT_SCORECARD_SECTIONS.map((d) => {
          const found = parsed.find((p) => p.key === d.key);
          return found ? { ...d, ...found } : { ...d, collapsed: false };
        });
      }
    } catch {}
    return DEFAULT_SCORECARD_SECTIONS.map((s) => ({ ...s, collapsed: false }));
  });
  const dragSectionRef = useRef(null);
  const dragBlockRef = useRef(null);

  const [wbs, setWbs] = useState(null);

  // Execution-plan creation affordance. `buildingPlan` holds the id of the
  // source (scorecard/scenario) currently generating so per-row buttons in
  // the trade-off table can show their own spinner; `null` = idle.
  const [buildingPlan, setBuildingPlan] = useState(null);
  const [buildPlanError, setBuildPlanError] = useState(null);
  // When a plan already exists for the targeted idea, the backend returns
  // `plan_exists` instead of overwriting. We stash the details here and show a
  // modal that lets the user open the existing plan or generate a fresh one.
  const [planExistsPrompt, setPlanExistsPrompt] = useState(null);

  const openExistingPlan = (scorecardId) => {
    const ideaQS = scorecardId ? `?idea=${encodeURIComponent(scorecardId)}` : '';
    navigate(`/workspace/${threadId}/${SENTINEL_EXECUTION}${ideaQS}`);
  };

  // Generate (and commit) an execution plan from a scorecard or trade-off
  // idea, then open the execution canvas. AI with heuristic fallback happens
  // server-side inside generate_ai_wbs. `source` is a stable key used only to
  // scope the per-button spinner. `force` skips the "plan already exists" gate
  // and regenerates a brand-new plan for the idea.
  const buildExecutionPlan = async ({ source, scorecard_id, scenario_id, force } = {}) => {
    if (buildingPlan) return; // one at a time
    setBuildPlanError(null);
    setBuildingPlan(source || scorecard_id || 'plan');
    try {
      const payload = { commit: true };
      if (scorecard_id) payload.scorecard_id = scorecard_id;
      if (scenario_id) payload.scenario_id = scenario_id;
      if (force) payload.force = true;
      const resp = await Jaspen.generateAiWbs(threadId, payload);
      // A plan already exists for this idea — let the user choose rather than
      // silently overwriting it.
      if (resp?.plan_exists) {
        setPlanExistsPrompt({
          scorecardId: resp.scorecard_id || scorecard_id || null,
          scorecardName: resp.scorecard_name || '',
          taskCount: Number(resp.task_count || 0),
          onGenerateNew: () => buildExecutionPlan({ source, scorecard_id, scenario_id, force: true }),
        });
        return;
      }
      // Open THIS idea's plan (scoped by ?idea=) so each plan stands alone.
      openExistingPlan(resp?.project_wbs?.scorecard_id || scorecard_id);
    } catch (err) {
      setBuildPlanError(
        (err && err.message) ? err.message : 'Could not build the execution plan. Please try again.'
      );
    } finally {
      setBuildingPlan(null);
    }
  };

  // Chat-driven build: generate the plan, then drop an inline sample card into
  // the conversation with an "Open in workspace" action (instead of jumping
  // straight to the execution canvas). `nextHistory` is the conversation up to
  // and including the user's affirmative; we replace the trailing pending
  // placeholder with the result card.
  async function buildExecutionPlanFromChat(nextHistory) {
    // Pick a seed: on a scorecard, this card's scorecard; on the trade-off
    // surface, the top-scoring idea (and name it so the user knows which).
    let seed = {};
    let seedLabel = displayTitle;
    if (isScorecard) {
      seed = { scorecard_id: scorecardId };
      seedLabel = _pickMeaningful(
        rendered?.project_name, snapshot?.name, snapshot?.project_name, displayTitle,
      ) || displayTitle;
    } else if (isTradeoff) {
      const top = (tradeoffIdeas || [])
        .map((s) => ({ raw: s, score: Number(s?.jaspen_score || s?.score || 0) }))
        .sort((a, b) => b.score - a.score)[0]?.raw;
      if (top) {
        const sid = String(top?.id || top?.analysis_id || top?.analysisId || '');
        if (sid) seed.scorecard_id = sid;
        const scn = top?.scenario_id || top?.scenarioId;
        if (scn) seed.scenario_id = scn;
        seedLabel = _pickMeaningful(top?.name, top?.project_name, top?.label, top?.title) || seedLabel;
      }
    }

    setChatHistory((prev) => {
      const arr = prev.slice(0, -1);
      return [...arr, { role: 'ai', text: `Building an execution plan for **${seedLabel}**…`, pending: true }];
    });

    try {
      const resp = await Jaspen.generateAiWbs(threadId, { ...seed, commit: true });
      if (resp?.plan_exists) {
        setChatHistory((prev) => {
          const arr = prev.slice(0, -1);
          return [...arr, {
            role: 'ai',
            text: `**${resp.scorecard_name || seedLabel}** already has an execution plan (${Number(resp.task_count || 0)} task${Number(resp.task_count || 0) === 1 ? '' : 's'}). Open the current plan, or generate a new one?`,
          }];
        });
        setPlanExistsPrompt({
          scorecardId: resp.scorecard_id || seed.scorecard_id || null,
          scorecardName: resp.scorecard_name || seedLabel,
          taskCount: Number(resp.task_count || 0),
          onGenerateNew: async () => {
            setChatBusy(true);
            try {
              const forced = await Jaspen.generateAiWbs(threadId, { ...seed, commit: true, force: true });
              const fWbs = forced?.project_wbs || forced?.wbs || forced || {};
              const fTasks = Array.isArray(fWbs?.tasks) ? fWbs.tasks : [];
              setChatHistory((prev) => [...prev, {
                role: 'ai',
                text: fTasks.length
                  ? `Here's a fresh execution plan for **${seedLabel}** — ${fTasks.length} task${fTasks.length === 1 ? '' : 's'}.`
                  : `I generated a new execution plan for **${seedLabel}**.`,
                execPlan: { label: seedLabel, tasks: fTasks.slice(0, 6), total: fTasks.length, scorecardId: seed.scorecard_id || null },
              }]);
            } catch (e) {
              setChatHistory((prev) => [...prev, { role: 'ai', text: `I couldn't regenerate the plan: ${String(e?.message || e || 'unknown error')}.` }]);
            } finally {
              setChatBusy(false);
            }
          },
        });
        return;
      }
      const planWbs = resp?.project_wbs || resp?.wbs || resp || {};
      const tasks = Array.isArray(planWbs?.tasks) ? planWbs.tasks : [];
      setChatHistory((prev) => {
        const arr = prev.slice(0, -1);
        return [...arr, {
          role: 'ai',
          text: tasks.length
            ? `Here's a draft execution plan for **${seedLabel}** — ${tasks.length} task${tasks.length === 1 ? '' : 's'} across the key workstreams. Open it in the workspace to edit, reassign, and track.`
            : `I generated an execution plan for **${seedLabel}**. Open it in the workspace to review.`,
          execPlan: { label: seedLabel, tasks: tasks.slice(0, 6), total: tasks.length, scorecardId: seed.scorecard_id || null },
        }];
      });
    } catch (err) {
      setChatHistory((prev) => {
        const arr = prev.slice(0, -1);
        return [...arr, {
          role: 'ai',
          text: `I couldn't build the execution plan: ${String(err?.message || err || 'unknown error')}. Want me to try again?`,
        }];
      });
    } finally {
      setChatBusy(false);
    }
  }

  // Fetch the artifact on mount. ALWAYS pull the bundle in parallel — even
  // when the focused endpoint succeeds — because the bundle carries the
  // chat messages we need for sensible title fallback when the scorecard
  // payload has a generic 'Baseline Analysis' name.
  useEffect(() => {
    let cancelled = false;
    async function load() {
      setLoading(true);
      setError(null);

      let target = null;
      let ov = {};

      // Always fetch the bundle in parallel (cheap-ish and gives us messages
      // for title fallback + the snapshot list for the tradeoff view).
      // Track bundle errors so the Trade-off view can surface them instead
      // of showing the misleading "Score an idea" empty state when the
      // real issue was a failed fetch.
      const bundlePromise = Jaspen.fetchBundle(threadId).catch((e) => {
        console.warn('[Workspace] bundle fetch failed:', e);
        setBundleError(String(e?.message || e || 'fetch failed'));
        return null;
      });

      // For scorecard artifacts, also fetch the focused endpoint for fast
      // first paint + authoritative overrides.
      let focusedPromise = Promise.resolve(null);
      if (isScorecard) {
        focusedPromise = Jaspen.getScorecardForWorkspace(threadId, scorecardId).catch((e) => {
          console.warn('[Workspace] focused scorecard fetch failed:', e);
          return null;
        });
      }

      // For execution artifacts, the WBS lives on a separate endpoint
      // (the bundle's project_wbs can lag for legacy threads). Hit
      // /threads/:tid/wbs directly so the canvas always sees the latest.
      let wbsPromise = Promise.resolve(null);
      if (isExecution) {
        // Scope to the open idea so each plan stands on its own. The server
        // also records this as the thread's active plan so the chat agent's
        // WBS mutation tools edit THIS idea, not another.
        wbsPromise = Jaspen.getThreadWbs(threadId, execIdeaId).catch((e) => {
          console.warn('[Workspace] WBS fetch failed (non-fatal):', e);
          return null;
        });
      }

      const [b, focused, wbsResp] = await Promise.all([bundlePromise, focusedPromise, wbsPromise]);
      if (cancelled) return;

      if (b) setBundle(b);
      // Server-side getThreadWbs is authoritative AND scoped to the open idea
      // (?scorecard_id). When we asked for a specific idea, trust that response
      // even when it's empty — falling back to the bundle's project_wbs here
      // would leak ANOTHER idea's plan (the bundle only carries the legacy
      // thread-level mirror, not this idea's plan). The bundle fallback is only
      // for legacy threads where we didn't scope by idea at all.
      // Record which idea the server says this plan belongs to (works even
      // on the legacy __execution__ route with no ?idea= in the URL).
      const respScorecardId = wbsResp?.scorecard_id ? String(wbsResp.scorecard_id) : null;
      setResolvedExecScorecardId(respScorecardId);
      // Canonicalize the URL: if we landed on the bare `__execution__` route
      // (no ?idea=) but the server knows which idea this plan belongs to, swap
      // to the idea-scoped URL. This keeps the per-idea chat key stable so the
      // conversation never splits between the bare and idea-scoped routes.
      if (!cancelled && isExecution && !ideaParam && respScorecardId) {
        navigate(
          `/workspace/${threadId}/${SENTINEL_EXECUTION}?idea=${encodeURIComponent(respScorecardId)}`,
          { replace: true }
        );
        return;
      }
      const respWbs = wbsResp?.project_wbs;
      const respHasTasks = respWbs && Array.isArray(respWbs.tasks) && respWbs.tasks.length > 0;
      if (respHasTasks) {
        setWbs(respWbs);
      } else if (execIdeaId && wbsResp && ('project_wbs' in wbsResp)) {
        // Idea explicitly requested — honor its (possibly empty) plan, no bleed.
        setWbs(respWbs || { name: 'Execution WBS', tasks: [] });
      } else if (b?.project_wbs && Array.isArray(b.project_wbs.tasks) && b.project_wbs.tasks.length > 0) {
        setWbs(b.project_wbs);
      } else if (respWbs) {
        setWbs(respWbs);
      }

      if (focused) {
        target = focused.scorecard || null;
        if (focused.display_overrides && typeof focused.display_overrides === 'object') {
          ov = focused.display_overrides;
        }
      }

      // For scorecards, fall back to the bundle's snapshot list if focused
      // endpoint didn't return a target.
      if (isScorecard && !target && b) {
        const snapshots = Array.isArray(b.scorecard_snapshots) ? b.scorecard_snapshots : [];
        target = snapshots.find(
          (s) => String(s?.id || s?.analysis_id || '') === String(scorecardId)
        ) || b.current_scorecard || b.baseline_scorecard || null;
        if (target?.display_overrides && typeof target.display_overrides === 'object' && Object.keys(ov).length === 0) {
          ov = target.display_overrides;
        }
      }

      setSnapshot(target);
      skipNextSaveRef.current = true;
      setOverrides(ov || {});

      if (isScorecard && !target) {
        setError(`Couldn't load this scorecard. Check that it exists in this thread.`);
      } else {
        setError(null);
      }
      setLoading(false);
    }
    void load();
    return () => { cancelled = true; };
  }, [threadId, scorecardId, isScorecard, execIdeaId]);

  // Load this artifact's chat. The server is the source of truth (durable,
  // cross-device); the localStorage cache is only an instant-paint buffer that
  // covers the window before the server responds and offline reloads. On key
  // change we first paint from the cache, then reconcile with the server.
  useEffect(() => {
    let cancelled = false;

    // Paint the cache immediately on key change (the first render already did
    // this via the lazy useState initializer). Flag it as a load so the save
    // effect doesn't echo stale data back under the new key.
    if (!firstChatLoadRef.current) {
      skipChatSaveRef.current = true;
      setChatHistory(_readWorkspaceChat(chatKey));
    }
    firstChatLoadRef.current = false;

    (async () => {
      try {
        const resp = await Jaspen.getWorkspaceChat(threadId, artifactId);
        if (cancelled) return;
        const serverMsgs = Array.isArray(resp?.messages) ? resp.messages : [];
        // Adopt the server copy when it has content, or when we have no local
        // turns to lose. If the server is empty but the cache holds unsynced
        // turns (e.g. a prior save failed), keep them — the save effect will
        // push them up and make the server consistent.
        const local = _readWorkspaceChat(chatKey);
        if (serverMsgs.length > 0 || local.length === 0) {
          skipChatSaveRef.current = true;
          setChatHistory(serverMsgs);
          _writeWorkspaceChat(chatKey, serverMsgs);
        }
      } catch (e) {
        console.warn('[Workspace] workspace-chat load failed (using local cache):', e);
      }
    })();

    return () => { cancelled = true; };
  }, [chatKey, threadId, artifactId]);

  // Persist on every change: write the local cache immediately (instant,
  // offline-resilient) and debounce a save to the server (authoritative).
  useEffect(() => {
    if (skipChatSaveRef.current) { skipChatSaveRef.current = false; return; }
    _writeWorkspaceChat(chatKey, chatHistory);
    if (chatSaveTimerRef.current) clearTimeout(chatSaveTimerRef.current);
    const durable = chatHistory.filter((m) => m && !m.pending);
    chatSaveTimerRef.current = setTimeout(() => {
      Jaspen.saveWorkspaceChat(threadId, artifactId, durable).catch((e) => {
        console.warn('[Workspace] workspace-chat save failed (kept in local cache):', e);
      });
    }, 600);
    return () => { if (chatSaveTimerRef.current) clearTimeout(chatSaveTimerRef.current); };
  }, [chatHistory, chatKey, threadId, artifactId]);

  // Pin the sidebar chat to the most recent message. On reload the thread would
  // otherwise render scrolled to the top, forcing the user to scroll down to
  // see where they left off. Runs on mount and whenever the history changes so
  // new replies stay in view.
  useEffect(() => {
    const el = chatScrollRef.current;
    if (!el) return;
    // rAF so the scroll happens after the new messages have laid out.
    const id = requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight;
    });
    return () => cancelAnimationFrame(id);
  }, [chatHistory]);

  // Force-save: flush the pending override save immediately (the "Save" button).
  // Some users want the reassurance of an explicit save even though edits auto-save.
  const flushSave = useCallback(async () => {
    if (!threadId || !scorecardId) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    try {
      setSaving(true);
      setSaveError(null);
      await Jaspen.patchScorecardOverrides(threadId, scorecardId, overrides);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1800);
    } catch (e) {
      setSaveError(String(e?.message || e || 'Failed to save'));
    } finally {
      setSaving(false);
    }
  }, [threadId, scorecardId, overrides]);

  // Debounced auto-save: any change to overrides is persisted ~500ms later.
  useEffect(() => {
    if (skipNextSaveRef.current) {
      skipNextSaveRef.current = false;
      return;
    }
    if (!threadId || !scorecardId) return;
    if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current);
    saveTimerRef.current = window.setTimeout(async () => {
      try {
        setSaving(true);
        setSaveError(null);
        await Jaspen.patchScorecardOverrides(threadId, scorecardId, overrides);
      } catch (e) {
        setSaveError(String(e?.message || e || 'Failed to save'));
      } finally {
        setSaving(false);
      }
    }, 500);
    return () => { if (saveTimerRef.current) window.clearTimeout(saveTimerRef.current); };
  }, [overrides, threadId, scorecardId]);

  useEffect(() => {
    if (!threadId || !scorecardId) return;
    try {
      localStorage.setItem(`jw-layout-${threadId}-${scorecardId}`, JSON.stringify(sectionLayout));
    } catch {}
  }, [sectionLayout, threadId, scorecardId]);

  const rendered = useMemo(() => applyOverrides(snapshot, overrides), [snapshot, overrides]);

  // Resolve the display title for THIS specific artifact. Priority:
  // override → meaningful scorecard fields → first user message in the
  // thread bundle. Never falls back to "Untitled idea" when the thread
  // has any user message to draw from.
  const displayTitle = useMemo(() => {
    // Sentinel artifact types: distinct top-bar titles
    if (scorecardId === SENTINEL_TRADEOFF) {
      const count = Array.isArray(bundle?.scorecard_snapshots) ? bundle.scorecard_snapshots.length : 0;
      return count > 0 ? `Trade-off · ${count} ideas` : 'Trade-off';
    }
    if (scorecardId === SENTINEL_EXECUTION) {
      return 'Execution Plan';
    }

    const ov = overrides && typeof overrides === 'object' ? overrides : {};
    const fromScorecard = _pickMeaningful(
      ov.title,
      snapshot?.name,
      snapshot?.project_name,
      snapshot?.title,
      snapshot?.initiative_name,
    );
    if (fromScorecard) return fromScorecard;

    const msgs = Array.isArray(bundle?.messages) ? bundle.messages : [];
    const firstUser = msgs.find(
      (m) => (m?.role === 'user' || m?.sender === 'user') &&
        String(m?.content || m?.text || '').trim().length > 0,
    );
    const fromMessage = _deriveFromMessage(firstUser?.content || firstUser?.text);
    if (fromMessage) return fromMessage;

    return 'Untitled idea';
  }, [snapshot, overrides, bundle, scorecardId]);

  // Synthesize the Trade-off comparison list ONCE so both the canvas render
  // and the sidebar chat's view_context see the exact same set of ideas. This
  // is the fix for "the trade-off chat thinks there's only one scorecard" —
  // the UI builds 3 ideas from snapshots/baseline/current/scenarios, and we
  // now hand that same list to the agent as authoritative.
  const tradeoffIdeas = useMemo(() => {
    const list = [];
    const known = new Set();
    const seed = (s, label, isBaseline) => {
      if (!s || typeof s !== 'object') return;
      const id = String(
        s.id || s.analysis_id || s.analysisId ||
        (isBaseline ? 'baseline' : `card_${list.length}`)
      );
      if (known.has(id)) return;
      known.add(id);
      list.push({
        ...s,
        id,
        analysis_id: s.analysis_id || id,
        label: s.label || label,
        isBaseline: Boolean(isBaseline || s.isBaseline),
      });
    };
    (Array.isArray(bundle?.scorecard_snapshots) ? bundle.scorecard_snapshots : [])
      .forEach((s, i) => seed(s, s?.label || `Version ${i + 1}`, s?.isBaseline));
    seed(bundle?.baseline_scorecard, 'Baseline', true);
    seed(bundle?.current_scorecard, 'Current', false);
    (Array.isArray(bundle?.scenarios) ? bundle.scenarios : []).forEach((entry, i) => {
      const inner = entry?.result || entry?.scorecard || entry?.analysis_result;
      if (!inner || typeof inner !== 'object') return;
      seed(
        { ...inner, label: inner.label || entry?.label || `Scenario ${i + 1}` },
        entry?.label || `Scenario ${i + 1}`,
        false,
      );
    });
    return list;
  }, [bundle]);

  // The idea whose execution plan is open (?idea=). Resolved from the same
  // de-duped snapshot list the trade-off table uses, so the execution header
  // names THIS idea (title + score) instead of always the baseline/winner.
  const execIdeaSnap = useMemo(() => {
    if (!isExecution) return null;
    // Prefer the explicit ?idea= from the URL; otherwise fall back to the
    // idea the server attributed this plan to (legacy __execution__ route).
    const lookupId = execIdeaId || resolvedExecScorecardId;
    if (!lookupId) return null;
    return (tradeoffIdeas || []).find(
      (s) => String(s?.id || s?.analysis_id || '') === String(lookupId)
    ) || null;
  }, [isExecution, execIdeaId, resolvedExecScorecardId, tradeoffIdeas]);

  const score = Number(rendered?.jaspen_score || 0);
  const ringColor = rendered?._accent_color || '#a0036c';
  const category = score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk';

  // Recommended scenario (first recommendation that has actionable text)
  const recs = Array.isArray(rendered?.recommendations) ? rendered.recommendations : [];
  const nextSteps = Array.isArray(rendered?.next_steps) ? rendered.next_steps : [];
  const recommendedScenario = (() => {
    // Manual override wins — the user can hand-edit the recommended scenario.
    if (rendered?.recommended_scenario) return rendered.recommended_scenario;
    if (recs[0]) {
      if (typeof recs[0] === 'string') return recs[0];
      if (recs[0]?.text) return recs[0].text;
      if (recs[0]?.action) return recs[0].action;
    }
    if (nextSteps[0] && typeof nextSteps[0] === 'string') return nextSteps[0];
    return null;
  })();

  // Set or remove a single cosmetic override. Auto-save fires from the
  // useEffect above on the next tick (debounced).
  // Download the current scorecard as Excel / Word via the backend exporter.
  async function downloadExport(format, ext, label) {
    try {
      const url = `${API_BASE}/api/v1/export/threads/${encodeURIComponent(threadId)}/scorecard/${format}?scorecard_id=${encodeURIComponent(scorecardId)}`;
      const res = await authFetch(url);
      if (!res.ok) {
        let msg = `${label} export failed.`;
        try { const j = await res.json(); if (j?.error) msg = j.error; } catch { /* not json */ }
        setSaveError(msg);
        return;
      }
      const blob = await res.blob();
      const cd = res.headers.get('Content-Disposition') || '';
      const m = cd.match(/filename="?([^"]+)"?/);
      const fname = (m && m[1]) || `scorecard.${ext}`;
      const objUrl = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = objUrl; a.download = fname;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(objUrl), 1500);
    } catch {
      setSaveError(`${label} export failed.`);
    }
  }

  async function copyShareLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      setLinkCopied(true);
      setTimeout(() => setLinkCopied(false), 1800);
    } catch {
      setSaveError('Could not copy the link.');
    }
  }

  function setOverride(key, value) {
    setOverrides((prev) => {
      const next = { ...prev };
      if (value === null || value === undefined || value === '') {
        delete next[key];
      } else {
        next[key] = value;
      }
      return next;
    });
  }

  async function resetOverrides() {
    // Warn: reset is destructive — it removes added sections AND all formatting.
    const ok = window.confirm(
      'Reset this scorecard to the original?\n\n'
      + 'This will DELETE any sections you added and reset ALL formatting — section '
      + 'sizes, order, brand color, and any edited text. This cannot be undone.'
    );
    if (!ok) return;
    skipNextSaveRef.current = true; // we'll do the save ourselves to clear remote
    setOverrides({});
    // Also reset the built-in section layout (sizes / order / collapse), which lives
    // in localStorage separately from display_overrides — this is the "formatting"
    // that a plain overrides-clear used to leave behind.
    setSectionLayout(DEFAULT_SCORECARD_SECTIONS.map((s) => ({ ...s, collapsed: false })));
    try { localStorage.removeItem(`jw-layout-${threadId}-${scorecardId}`); } catch {}
    try {
      setSaving(true);
      // Pass nulls for each known key so the backend removes them — INCLUDING
      // custom_blocks, so added sections don't reappear on reload.
      await Jaspen.patchScorecardOverrides(threadId, scorecardId, {
        title: null, subtitle: null, executive_summary: null,
        accent_color: null, theme: null, narrative: null,
        top_risks: null, recommended_scenario: null,
        custom_blocks: null,
      });
    } catch (e) {
      setSaveError(String(e?.message || e || 'Failed to reset'));
    } finally {
      setSaving(false);
    }
  }

  async function sendChat(overrideText) {
    // overrideText is a string when a choice-prompt option is clicked; otherwise
    // this is a normal send (onClick passes an event, which we ignore).
    const text = (typeof overrideText === 'string' ? overrideText : chatInput).trim();
    if (!text || chatBusy) return;
    // Optimistic user message
    const userTurn = { role: 'user', text };
    const nextHistory = [...chatHistory, userTurn];
    setChatHistory([...nextHistory, { role: 'ai', text: '…', pending: true }]);
    setChatInput('');
    setChatBusy(true);

    // Chat-driven execution-plan creation. On a scorecard or trade-off surface,
    // if the user asks for an execution plan (or says "yes" right after Jaspen
    // offered one), build it inline and show a sample card instead of a normal
    // chat reply. Skip on the execution surface — they're already looking at it.
    if (!isExecution) {
      const lastAi = [...chatHistory].reverse().find((m) => m.role === 'ai' && !m.pending);
      if (_detectExecPlanIntent(text, lastAi?.text)) {
        await buildExecutionPlanFromChat(nextHistory);
        return;
      }
    }

    try {
      // Build a thin analysis_context so the agent grounds replies in this
      // artifact. We keep it compact — only the fields the agent needs to
      // reason about this canvas. Manual edits still flow through their own
      // patch endpoints; this chat is for Q&A + AI-assisted edits.
      const ctx = {
        thread_id: threadId,
        artifact_kind: isExecution ? 'execution_plan' : isTradeoff ? 'tradeoff' : 'scorecard',
        scorecard_id: isScorecard ? scorecardId : null,
        scorecard_name: isScorecard ? (snapshot?.name || displayTitle) : displayTitle,
        snapshot: isScorecard ? snapshot : null,
        wbs_summary: isExecution && Array.isArray(wbs?.tasks)
          ? { tasks: wbs.tasks.length }
          : null,
      };

      // Build the view_context the backend actually grounds on. This is the
      // contextual-awareness fix: tell the agent which surface is open and
      // hand it the on-screen ideas (trade-off) or task breakdown (execution).
      const viewContext = {
        current_view: isExecution ? 'execution' : isTradeoff ? 'tradeoff' : 'scorecard',
        active_tab: isExecution ? 'execution' : isTradeoff ? 'tradeoff' : 'scorecard',
      };
      if (isScorecard) {
        viewContext.active_scorecard_id = scorecardId;
        // Pass the active scorecard's NAME + score so the agent knows exactly
        // which idea is on screen. The session only persists one scorecard, so
        // an ID alone isn't resolvable when the user is viewing a synthesized
        // sibling — this stops the "which of the three?" clarifying question.
        const activeName = _pickMeaningful(
          rendered?.project_name, snapshot?.name, snapshot?.project_name,
          snapshot?.title, snapshot?.initiative_name, displayTitle,
        );
        if (activeName) viewContext.active_scorecard_name = activeName;
        const activeScore = Number(rendered?.jaspen_score || snapshot?.jaspen_score || 0);
        if (activeScore) viewContext.active_scorecard_score = activeScore;
      }
      if (isTradeoff) {
        // The same list the canvas renders — names + scores — so the agent
        // sees every idea being compared, not just the single stored snapshot.
        viewContext.visible_ideas = (tradeoffIdeas || [])
          .map((s) => ({
            name: _pickMeaningful(
              s?.label, s?.name, s?.project_name, s?.title, s?.initiative_name,
            ) || 'Untitled idea',
            score: Number(s?.jaspen_score || s?.score || 0) || undefined,
          }))
          .filter((s) => s.name);
      }
      if (isExecution && execIdeaId) {
        // Tell the backend which idea's plan is open so the chat agent's WBS
        // mutation tools (add/update/remove task) edit THIS plan, not another —
        // and so the agent grounds on THIS idea (name + score), never baseline.
        viewContext.active_scorecard_id = execIdeaId;
        const ideaName = _pickMeaningful(
          execIdeaSnap?.name, execIdeaSnap?.project_name, execIdeaSnap?.title,
          execIdeaSnap?.label,
        );
        if (ideaName) viewContext.active_scorecard_name = ideaName;
        const ideaScore = Number(execIdeaSnap?.jaspen_score || execIdeaSnap?.score || 0);
        if (ideaScore) viewContext.active_scorecard_score = ideaScore;
      }
      if (isExecution && Array.isArray(wbs?.tasks)) {
        const byStatus = wbs.tasks.reduce((acc, t) => {
          const raw = String(t?.status || 'todo').toLowerCase().replace(/[\s-]+/g, '_');
          const key = raw === 'in_progress' || raw === 'inprogress' ? 'in_progress'
            : raw === 'blocked' ? 'blocked'
            : raw === 'done' || raw === 'complete' || raw === 'completed' ? 'done'
            : 'todo';
          acc[key] = (acc[key] || 0) + 1;
          return acc;
        }, {});
        viewContext.wbs_summary = { total_tasks: wbs.tasks.length, by_status: byStatus };
      }

      // Conversation history (Anthropic-friendly role+content shape).
      // Prepend the originating thread conversation so the agent has BOTH the
      // context that led the user into this workspace AND everything they've
      // said here since. Workspace turns live in localStorage (not in
      // bundle.messages), so there's no duplication.
      const originContext = _originContextFromBundle(bundle);
      const workspaceTurns = nextHistory.map((m) => ({
        role: m.role === 'user' ? 'user' : 'assistant',
        content: String(m.text || ''),
      }));
      const history = [...originContext, ...workspaceTurns];

      const resp = await Jaspen.chat({
        message: text,
        conversation_history: history,
        analysis_context: ctx,
        view_context: viewContext,
        analysis_id: threadId,
      });
      const replyText = String(resp?.text || resp?.response || resp?.reply || '').trim()
        || 'Got it — I noted that. (No reply payload was returned.)';
      setChatHistory((prev) => {
        // Replace the trailing pending placeholder
        const arr = prev.slice(0, -1);
        return [...arr, { role: 'ai', text: replyText }];
      });

      // If the agent mutated anything, reflect it on EVERY surface without a
      // manual reload. The open card snapshot updates inline below (fast path),
      // but the sidebar idea list + trade-off table read from `bundle`, and the
      // execution canvas reads from `wbs` — so re-fetch those too when a
      // relevant tool ran. This is what kills the "I had to hard-refresh" feel
      // after a chat rename / re-score / task edit.
      const muts = Array.isArray(resp?.mutations) ? resp.mutations : [];
      const anySuccess = muts.some((m) => m && m.success);
      if (anySuccess) {
        // Re-pull the bundle so sidebar/trade-off names + scores refresh
        // (covers rename_thread, generate_scorecard, scenario edits, etc.).
        try {
          const fresh = await Jaspen.fetchBundle(threadId);
          if (fresh) setBundle(fresh);
        } catch (e) {
          console.warn('[workspace] post-edit bundle refetch failed:', e);
        }
        // Execution view: re-pull the open idea's WBS if a task tool ran.
        if (isExecution) {
          const wbsTouched = muts.some(
            (m) => m && m.success && /wbs|execution|task/i.test(String(m.tool || ''))
          );
          if (wbsTouched) {
            try {
              const w = await Jaspen.getThreadWbs(threadId, execIdeaId);
              const pw = w?.project_wbs;
              if (pw && Array.isArray(pw.tasks)) setWbs(pw);
            } catch (e) {
              console.warn('[workspace] post-edit WBS refetch failed:', e);
            }
          }
        }
      }

      // If the agent edited or re-scored the OPEN scorecard in place, reflect
      // it on the canvas without a manual reload. Prefer the updated scorecard
      // the agent returned; otherwise re-fetch the authoritative copy.
      if (isScorecard && scorecardId) {
        const editedHere = muts.some(
          (m) => m && m.success && (
            m.tool === 'patch_scorecard'
            || m.tool === 'generate_scorecard'
            || m.tool === 'rename_thread'
          )
        );
        if (editedHere) {
          const acts = Array.isArray(resp?.actions) ? resp.actions : [];
          const updated = acts
            .map((a) => a?.result?.updated_scorecard)
            .find((sc) => sc && String(sc.id || sc.analysis_id || '') === String(scorecardId));
          if (updated && typeof updated === 'object') {
            skipNextSaveRef.current = true;
            setSnapshot(updated);
            // Re-sync local cosmetic overrides from the authoritative card so a
            // stale override (e.g. an old display_overrides.title) can't shadow a
            // chat rename. displayTitle reads ov.title first, so without this the
            // canvas would keep the old name until a hard refresh.
            if (updated.display_overrides && typeof updated.display_overrides === 'object') {
              skipNextSaveRef.current = true;
              setOverrides(updated.display_overrides);
            }
          } else {
            // No inline payload (or it targeted a re-scored id) — re-fetch.
            try {
              const fresh = await Jaspen.getScorecardForWorkspace(threadId, scorecardId);
              const sc = fresh?.scorecard;
              if (sc && typeof sc === 'object') {
                skipNextSaveRef.current = true;
                setSnapshot(sc);
                if (sc.display_overrides && typeof sc.display_overrides === 'object') {
                  skipNextSaveRef.current = true;
                  setOverrides(sc.display_overrides);
                }
              }
            } catch (e) {
              console.warn('[workspace] post-edit scorecard refetch failed:', e);
            }
          }
        }
      }
    } catch (e) {
      console.error('[workspace chat] failed:', e);
      setChatHistory((prev) => {
        const arr = prev.slice(0, -1);
        return [
          ...arr,
          { role: 'ai', text: `Jaspen couldn't reply: ${String(e?.message || e || 'unknown error')}. Try again in a moment.` },
        ];
      });
    } finally {
      setChatBusy(false);
    }
  }

  // --- Loading / error states ---
  if (loading) {
    return (
      <div style={{ display:'flex', alignItems:'center', justifyContent:'center', height:'100vh', color:'#475569', fontSize:14 }}>
        Loading workspace…
      </div>
    );
  }
  // For scorecard routes we need a snapshot; tradeoff/execution don't.
  if (error || (isScorecard && !snapshot)) {
    return (
      <div style={{ display:'flex', flexDirection:'column', alignItems:'center', justifyContent:'center', height:'100vh', gap:12, color:'#475569' }}>
        <div style={{ fontSize:15, fontWeight:600, color:'#0f172a' }}>Couldn't open this artifact</div>
        <div style={{ fontSize:13 }}>{error || 'Scorecard not found in this thread.'}</div>
        <Link to="/new" style={{ marginTop:8, padding:'8px 14px', borderRadius:8, background:'#0f172a', color:'#fff', textDecoration:'none', fontSize:13 }}>
          Back to Jaspen
        </Link>
      </div>
    );
  }

  return (
    <div data-ws-root style={{ display:'flex', height:'100vh', background:'#f7f8fa', fontFamily:'Inter Tight, system-ui, sans-serif', position:'relative' }}>
      <style>{`
        /* Custom-block grid: brand-tinted drag placeholder + always-visible SE resize handle */
        .jw-block-grid .react-grid-placeholder { background: rgba(160, 3, 108, 0.12) !important; border-radius: 10px; }
        .jw-block-grid .react-resizable-handle { opacity: 0.55; }
        .jw-block-grid .react-grid-item:hover .react-resizable-handle { opacity: 1; }
        @media print {
          * { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
          [data-ws-sidebar] { display: none !important; }
          [data-ws-topbar] { display: none !important; }
          [data-ws-root] { display: block !important; height: auto !important; }
          [data-ws-main] { width: 100% !important; overflow: visible !important; }
          [data-ws-canvas] { overflow: visible !important; padding: 0 !important; }
        }
      `}</style>

      {/* === "Plan already exists" choice modal === */}
      {planExistsPrompt && (
        <div
          role="presentation"
          onClick={() => setPlanExistsPrompt(null)}
          style={{
            position:'fixed', inset:0, zIndex:9999, background:'rgba(15,23,42,0.45)',
            display:'flex', alignItems:'center', justifyContent:'center', padding:16,
          }}
        >
          <div
            role="dialog"
            aria-modal="true"
            onClick={(e) => e.stopPropagation()}
            style={{
              width:'min(440px, 100%)', background:'#fff', borderRadius:14,
              boxShadow:'0 20px 60px rgba(15,23,42,0.3)', padding:'22px 22px 18px',
              fontFamily:'Inter Tight, system-ui, sans-serif',
            }}
          >
            <div style={{ fontSize:16, fontWeight:700, color:'#0f172a', marginBottom:8 }}>
              Execution plan already exists
            </div>
            <div style={{ fontSize:13.5, color:'#475569', lineHeight:1.55, marginBottom:18 }}>
              {planExistsPrompt.scorecardName ? <><strong>{planExistsPrompt.scorecardName}</strong> already has an execution plan</> : 'This idea already has an execution plan'}
              {planExistsPrompt.taskCount ? ` (${planExistsPrompt.taskCount} task${planExistsPrompt.taskCount === 1 ? '' : 's'})` : ''}.
              {' '}Open the current plan, or generate a new one to replace it?
            </div>
            <div style={{ display:'flex', gap:10, justifyContent:'flex-end', flexWrap:'wrap' }}>
              <button
                type="button"
                onClick={() => {
                  const fn = planExistsPrompt.onGenerateNew;
                  setPlanExistsPrompt(null);
                  if (typeof fn === 'function') fn();
                }}
                style={{
                  padding:'9px 14px', borderRadius:9, border:'1px solid #cbd5e1',
                  background:'#fff', color:'#0f172a', fontSize:13, fontWeight:600, cursor:'pointer',
                }}
              >
                Generate new plan
              </button>
              <button
                type="button"
                onClick={() => {
                  const sid = planExistsPrompt.scorecardId;
                  setPlanExistsPrompt(null);
                  openExistingPlan(sid);
                }}
                style={{
                  padding:'9px 16px', borderRadius:9, border:'1px solid #a0036c',
                  background:'#a0036c', color:'#fff', fontSize:13, fontWeight:600, cursor:'pointer',
                }}
              >
                Open current plan
              </button>
            </div>
          </div>
        </div>
      )}

      {/* === LEFT SIDEBAR: scoped chat === */}
      <aside
        data-ws-sidebar
        style={{
          width: sidebarOpen ? 340 : 0,
          flexShrink: 0,
          background: '#fff',
          borderRight: sidebarOpen ? '1px solid #e6eaf2' : 'none',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden',
          transition: 'width 0.25s ease',
          position: 'relative',
        }}
      >
        <div style={{ padding:'14px 16px', borderBottom:'1px solid #e6eaf2' }}>
          <div style={{ fontSize:12, color:'#64748b', textTransform:'uppercase', letterSpacing:'0.06em', fontWeight:600 }}>
            Workspace · Beta
          </div>
          <div style={{ fontSize:14, color:'#0f172a', marginTop:4, fontWeight:600 }}>
            {displayTitle}
          </div>
          <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>
            {isExecution
              ? <>Editing execution plan. <span style={{ color:'#0f172a', fontWeight:500 }}>Manual edits are free</span>; AI edits cost credits.</>
              : isTradeoff
                ? <>Viewing trade-off comparison. <span style={{ color:'#0f172a', fontWeight:500 }}>Ask Jaspen anything</span> about the comparison.</>
                : <>Editing cosmetic fields. <span style={{ color:'#0f172a', fontWeight:500 }}>Manual edits are free</span>; AI edits cost credits.</>}
          </div>
        </div>

        {/* Chat thread */}
        <div ref={chatScrollRef} style={{ flex:1, overflow:'auto', padding:'12px 16px', display:'flex', flexDirection:'column', gap:10 }}>
          {chatHistory.length === 0 && (
            <div style={{ fontSize:12, color:'#94a3b8', lineHeight:1.5 }}>
              {isExecution
                ? 'Ask Jaspen to reassign tasks, shift dates, or regenerate the plan — or click any cell on the canvas to edit directly.'
                : 'Ask Jaspen to rewrite copy, adjust tone, or tweak styling — or click anything on the canvas to edit directly.'}
            </div>
          )}
          {chatHistory.map((m, i) => {
            const isAi = m.role !== 'user';
            const parsed = isAi && !m.pending ? parseChoicePrompt(m.text) : { text: m.text, choice: null };
            const isLastMsg = i === chatHistory.length - 1;
            return (
            <React.Fragment key={i}>
            <div
              style={{
                alignSelf: m.role === 'user' ? 'flex-end' : 'flex-start',
                maxWidth:'90%', padding:'8px 12px', borderRadius:10,
                background: m.role === 'user' ? '#0f172a' : '#f1f5f9',
                color: m.role === 'user' ? '#fff' : '#0f172a',
                fontSize:13, lineHeight:1.5,
              }}
            >
              {m.role === 'user' ? (
                m.text
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    p: ({ children }) => <p style={{ margin:'0 0 6px', lineHeight:1.5 }}>{children}</p>,
                    h1: ({ children }) => <p style={{ margin:'6px 0 4px', fontWeight:700, fontSize:14 }}>{children}</p>,
                    h2: ({ children }) => <p style={{ margin:'6px 0 4px', fontWeight:700, fontSize:13 }}>{children}</p>,
                    h3: ({ children }) => <p style={{ margin:'6px 0 4px', fontWeight:600, fontSize:13 }}>{children}</p>,
                    ul: ({ children }) => <ul style={{ margin:'4px 0', paddingLeft:16 }}>{children}</ul>,
                    ol: ({ children }) => <ol style={{ margin:'4px 0', paddingLeft:16 }}>{children}</ol>,
                    li: ({ children }) => <li style={{ marginBottom:2, lineHeight:1.45 }}>{children}</li>,
                    strong: ({ children }) => <strong style={{ fontWeight:600 }}>{children}</strong>,
                    table: ({ children }) => <table style={{ borderCollapse:'collapse', fontSize:12, margin:'6px 0', width:'100%' }}>{children}</table>,
                    th: ({ children }) => <th style={{ border:'1px solid #cbd5e1', padding:'3px 6px', background:'#e2e8f0', textAlign:'left' }}>{children}</th>,
                    td: ({ children }) => <td style={{ border:'1px solid #cbd5e1', padding:'3px 6px' }}>{children}</td>,
                    code: ({ children }) => <code style={{ background:'#e2e8f0', borderRadius:3, padding:'1px 4px', fontSize:12 }}>{children}</code>,
                  }}
                >
                  {m.pending ? '…' : String(parsed.text || '')}
                </ReactMarkdown>
              )}
              {m.execPlan && (
                <div style={{ marginTop:8, background:'#fff', border:'1px solid #e6eaf2', borderRadius:10, overflow:'hidden' }}>
                  <div style={{ padding:'8px 10px', borderBottom:'1px solid #eef1f6', display:'flex', alignItems:'center', gap:6 }}>
                    <FontAwesomeIcon icon={faDiagramProject} style={{ color:'#a0036c', fontSize:12 }} />
                    <span style={{ fontSize:11.5, fontWeight:600, color:'#0f172a' }}>
                      Execution plan · {m.execPlan.total} task{m.execPlan.total === 1 ? '' : 's'}
                    </span>
                  </div>
                  <div style={{ padding:'6px 10px' }}>
                    {(m.execPlan.tasks || []).map((t, ti) => (
                      <div key={ti} style={{ display:'flex', gap:6, alignItems:'baseline', padding:'3px 0', fontSize:11.5, color:'#334155' }}>
                        <span style={{ color:'#a0036c', fontFamily:'JetBrains Mono,monospace', fontSize:10 }}>{String(ti + 1).padStart(2, '0')}</span>
                        <span style={{ flex:1, lineHeight:1.4 }}>{String(t?.title || t?.name || t?.task || 'Untitled task')}</span>
                      </div>
                    ))}
                    {m.execPlan.total > (m.execPlan.tasks || []).length && (
                      <div style={{ fontSize:10.5, color:'#94a3b8', paddingTop:2 }}>
                        +{m.execPlan.total - (m.execPlan.tasks || []).length} more…
                      </div>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => navigate(
                      `/workspace/${threadId}/${SENTINEL_EXECUTION}` +
                      (m.execPlan.scorecardId ? `?idea=${encodeURIComponent(m.execPlan.scorecardId)}` : '')
                    )}
                    style={{
                      width:'100%', padding:'8px 10px', border:'none', borderTop:'1px solid #eef1f6',
                      background:'#0f172a', color:'#fff', cursor:'pointer', fontSize:12, fontWeight:600,
                      display:'flex', alignItems:'center', justifyContent:'center', gap:6,
                    }}
                  >
                    <FontAwesomeIcon icon={faDiagramProject} style={{ fontSize:11 }} />
                    Open in workspace
                  </button>
                </div>
              )}
            </div>
            {parsed.choice && (
              <div style={{ alignSelf:'flex-start', maxWidth:'94%' }}>
                <ChoicePrompt
                  choice={parsed.choice}
                  accent={ringColor}
                  disabled={!isLastMsg || chatBusy}
                  onChoose={(v) => sendChat(v)}
                />
              </div>
            )}
            </React.Fragment>
            );
          })}
        </div>

        {/* Chat input */}
        <div style={{ padding:'10px 12px 14px', borderTop:'1px solid #e6eaf2' }}>
          <div style={{ display:'flex', alignItems:'flex-end', gap:6, background:'#f7f8fa', borderRadius:10, padding:'8px 10px' }}>
            <textarea
              ref={chatComposerRef}
              rows={1}
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); } }}
              placeholder={chatBusy ? 'Jaspen is replying…' : 'Describe a change…'}
              disabled={chatBusy}
              style={{ flex:1, border:'none', outline:'none', background:'transparent', fontSize:13, color:'#0f172a', resize:'none', maxHeight:140, overflowY:'auto', lineHeight:1.45, fontFamily:'inherit', padding:0 }}
            />
            <button
              onClick={sendChat}
              disabled={!chatInput.trim() || chatBusy}
              style={{
                width:30, height:30, borderRadius:8, border:'none',
                background: (chatInput.trim() && !chatBusy) ? '#0f172a' : '#cbd5e1',
                color:'#fff', cursor: (chatInput.trim() && !chatBusy) ? 'pointer' : 'not-allowed',
                display:'flex', alignItems:'center', justifyContent:'center',
              }}
              aria-label="Send"
            >
              <FontAwesomeIcon icon={faPaperPlane} style={{ fontSize:11 }} />
            </button>
          </div>
        </div>
      </aside>

      {/* Sidebar toggle tab */}
      <button
        data-ws-sidebar
        onClick={() => setSidebarOpen((o) => !o)}
        title={sidebarOpen ? 'Collapse chat' : 'Expand chat'}
        style={{
          position: 'absolute',
          left: sidebarOpen ? 332 : 0,
          top: '50%',
          transform: 'translateY(-50%)',
          zIndex: 10,
          width: 20,
          height: 48,
          borderRadius: sidebarOpen ? '0 6px 6px 0' : '0 6px 6px 0',
          border: '1px solid #e6eaf2',
          borderLeft: sidebarOpen ? 'none' : '1px solid #e6eaf2',
          background: '#fff',
          color: '#64748b',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          fontSize: 10,
          transition: 'left 0.25s ease',
          padding: 0,
        }}
        aria-label={sidebarOpen ? 'Collapse chat panel' : 'Expand chat panel'}
      >
        {sidebarOpen ? '‹' : '›'}
      </button>

      {/* === CENTER: canvas === */}
      <main data-ws-main style={{ flex:1, display:'flex', flexDirection:'column', overflow:'hidden' }}>
        <div data-ws-topbar style={{ padding:'18px 28px', borderBottom:'1px solid #e6eaf2', background:'#fff', display:'flex', alignItems:'center', justifyContent:'space-between' }}>
          <div style={{ display:'flex', alignItems:'baseline', gap:10 }}>
            {isScorecard ? (
              // The top-bar title is the most prominent one — make it inline-
              // editable too (not just the in-card title) so a manual rename
              // works from where the user actually looks. Commits to the same
              // cosmetic override the in-card title uses. Trade-off/execution
              // titles are derived (or edited in their own canvas), so they stay
              // static here.
              <EditableText
                value={displayTitle}
                onCommit={(v) => setOverride('title', v)}
                style={{ margin:0, fontSize:18, fontWeight:600, color:'#0f172a' }}
              />
            ) : (
              <h1 style={{ margin:0, fontSize:18, fontWeight:600, color:'#0f172a' }}>{displayTitle}</h1>
            )}
            <span style={{ padding:'2px 8px', borderRadius:10, background:'#fef3c7', color:'#92400e', fontSize:10, fontWeight:600, letterSpacing:'0.04em' }}>
              BETA
            </span>
            {saving && (
              <span style={{ fontSize:11, color:'#94a3b8' }}>Saving…</span>
            )}
            {!saving && saveError && (
              <span style={{ fontSize:11, color:'#dc2626' }} title={saveError}>Save failed</span>
            )}
            {!saving && !saveError && Object.keys(overrides).length > 0 && (
              <span style={{ fontSize:11, color:'#94a3b8' }}>Saved</span>
            )}
          </div>
          <div style={{ display:'flex', gap:8 }}>
            {/* Force-save: explicit reassurance even though edits auto-save. */}
            {isScorecard && (
              <button
                type="button"
                onClick={flushSave}
                disabled={saving}
                title="Save now"
                style={{
                  padding:'8px 12px', borderRadius:8, border:'1px solid #d6dce6',
                  background: savedFlash ? '#ecfdf3' : '#fff',
                  color: savedFlash ? '#0d7a3e' : '#0f172a',
                  cursor: saving ? 'wait' : 'pointer', fontSize:13, fontWeight:500,
                }}
              >
                {saving ? 'Saving…' : savedFlash ? 'Saved ✓' : 'Save'}
              </button>
            )}
            {/* Reset only applies to scorecard cosmetic overrides. The
                execution plan has its own Undo/Redo inside the canvas, and
                the trade-off surface has nothing to reset — so we hide the
                button there (it was permanently disabled = "doesn't work"). */}
            {isScorecard && (
              <button
                type="button"
                onClick={resetOverrides}
                disabled={Object.keys(overrides).length === 0}
                title={Object.keys(overrides).length === 0 ? 'No manual edits to reset' : 'Reset manual edits to the original'}
                style={{
                  padding:'8px 12px', borderRadius:8, border:'1px solid #d6dce6',
                  background:'#fff', color:'#0f172a', cursor: Object.keys(overrides).length === 0 ? 'not-allowed' : 'pointer',
                  fontSize:13, opacity: Object.keys(overrides).length === 0 ? 0.5 : 1,
                }}
              >
                <FontAwesomeIcon icon={faRotateLeft} style={{ marginRight:6 }} />
                Reset
              </button>
            )}
            {isScorecard && (
              // #4 custom colors: set the scorecard's brand accent. Writes
              // display_overrides.accent_color -> rendered._accent_color -> ringColor,
              // which the score ring, category label, recommendation, and primary
              // action all use. Carried into PDF/Word exports server-side.
              <input
                type="color"
                value={/^#[0-9a-fA-F]{6}$/.test(ringColor) ? ringColor : '#a0036c'}
                onChange={(e) => setOverride('accent_color', e.target.value)}
                title="Scorecard accent color"
                aria-label="Scorecard accent color"
                style={{ width:30, height:30, padding:2, border:'1px solid #e6eaf2', borderRadius:8, background:'#fff', cursor:'pointer' }}
              />
            )}
            {isScorecard && (
              <button
                type="button"
                onClick={() => buildExecutionPlan({ source: 'scorecard', scorecard_id: scorecardId })}
                disabled={Boolean(buildingPlan)}
                title={buildPlanError || 'Generate an execution plan from this scorecard'}
                style={{
                  padding:'8px 12px', borderRadius:8,
                  border: buildPlanError ? '1px solid #dc2626' : `1px solid ${ringColor}`,
                  background:'#fff', color: buildPlanError ? '#dc2626' : ringColor,
                  cursor: buildingPlan ? 'wait' : 'pointer', fontSize:13, fontWeight:600,
                  opacity: buildingPlan ? 0.7 : 1,
                }}
              >
                <FontAwesomeIcon
                  icon={buildingPlan ? faSpinner : faDiagramProject}
                  spin={Boolean(buildingPlan)}
                  style={{ marginRight:6 }}
                />
                {buildingPlan ? 'Building…' : 'Build Execution Plan'}
              </button>
            )}
            <div style={{ position:'relative' }}>
              <button
                type="button"
                onClick={() => setExportMenuOpen((o) => !o)}
                style={{ padding:'8px 14px', borderRadius:8, border:'none', background:'#0f172a', color:'#fff', cursor:'pointer', fontSize:13, fontWeight:500, display:'flex', alignItems:'center', gap:6 }}
              >
                <FontAwesomeIcon icon={faDownload} />
                Download / Share
                <span style={{ fontSize:10, opacity:0.8 }}>▾</span>
              </button>
              {exportMenuOpen && (
                <>
                  <div onClick={() => setExportMenuOpen(false)} style={{ position:'fixed', inset:0, zIndex:40 }} />
                  <div style={{ position:'absolute', top:'calc(100% + 6px)', right:0, zIndex:41, background:'#fff', border:'1px solid #e6eaf2', borderRadius:10, boxShadow:'0 8px 24px rgba(22,31,59,0.12)', minWidth:210, padding:6, display:'flex', flexDirection:'column' }}>
                    {[
                      ...(isScorecard ? [
                        { label:'Download PDF', act:() => downloadExport('pdf','pdf','PDF') },
                        { label:'Download Word', act:() => downloadExport('docx','docx','Word') },
                        // MVP: Excel + PowerPoint are visible but disabled until polished
                        // (PPTX needs condensing to 1–2 slides; Excel grid pending).
                        { label:'Download Excel', disabled:true },
                        { label:'Download PowerPoint', disabled:true },
                      ] : []),
                      { label: linkCopied ? 'Link copied ✓' : 'Copy link', act: copyShareLink, keepOpen:true, divider:true },
                    ].map((it, i) => (
                      <React.Fragment key={i}>
                        {it.divider && isScorecard && <div style={{ height:1, background:'#eef1f6', margin:'4px 2px' }} />}
                        <button
                          type="button"
                          disabled={Boolean(it.disabled)}
                          onClick={() => { if (it.disabled) return; it.act?.(); if (!it.keepOpen) setExportMenuOpen(false); }}
                          style={{ textAlign:'left', padding:'8px 10px', border:'none', background:'transparent', color: it.disabled ? '#aab2c0' : (it.label.includes('copied') ? '#0d7a3e' : '#0f172a'), cursor: it.disabled ? 'default' : 'pointer', fontSize:13, borderRadius:6, display:'flex', justifyContent:'space-between', alignItems:'center', gap:10 }}
                          onMouseEnter={(e) => { if (!it.disabled) e.currentTarget.style.background = '#f5f7fa'; }}
                          onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                        >
                          <span>{it.label}</span>
                          {it.disabled && <span style={{ fontSize:10, color:'#aab2c0', fontWeight:600 }}>Soon</span>}
                        </button>
                      </React.Fragment>
                    ))}
                  </div>
                </>
              )}
            </div>
            {/* Single, always-visible Back to Jaspen link, right of Download/Share —
                replaces the sidebar + collapsed variants so there's one consistent
                control across surfaces. Preserves the thread via ?sid. */}
            <Link
              to={`/new?sid=${encodeURIComponent(threadId)}`}
              title="Back to Jaspen"
              style={{ display:'inline-flex', alignItems:'center', gap:6, color:'#475569', textDecoration:'none', fontSize:13, paddingLeft:4, whiteSpace:'nowrap' }}
            >
              <FontAwesomeIcon icon={faArrowLeft} />
              Back to Jaspen
            </Link>
          </div>
        </div>

        {/* Canvas */}
        <div data-ws-canvas style={{ flex:1, overflow:'auto', padding: isTradeoff ? 0 : '32px 48px' }}>
          {isTradeoff ? (
            // Trade-off canvas: full TradeoffView render. Cosmetic edits
            // (title overrides etc.) will land in v1.1 — this v1 shows the
            // full comparison surface inside the Workspace shell so the user
            // can already 'view large' and download.
            //
            // We merge baseline + current into the snapshots list because for
            // older threads `bundle.scorecard_snapshots` may be empty even
            // when a baseline exists — TradeoffView's empty state would then
            // hide a comparison that actually has data to show.
            <div style={{ display:'flex', flexDirection:'column' }}>
              {(() => {
                // Use the shared `tradeoffIdeas` memo so the canvas and the
                // sidebar chat's view_context render the exact same set of
                // ideas (snapshots + baseline + current + scenarios, de-duped).
                const list = tradeoffIdeas;

                // Diagnostic visibility — log every source the Trade-off view
                // pulled from so the user (and we) can see exactly where the
                // data came from / why it might be empty.
                if (typeof console !== 'undefined' && console.log) {
                  console.log('[Trade-off Workspace]', {
                    threadId,
                    bundleLoaded: Boolean(bundle),
                    bundleError,
                    snapshotsFromBundle: (bundle?.scorecard_snapshots || []).length,
                    hasBaseline: Boolean(bundle?.baseline_scorecard),
                    hasCurrent: Boolean(bundle?.current_scorecard),
                    scenariosFromBundle: (bundle?.scenarios || []).length,
                    listLength: list.length,
                  });
                }

                // Honest error path: when bundle didn't load at all, say so
                // instead of falling through to "Score an idea" — that
                // empty-state was misleading users into thinking they had
                // no scorecards when the real cause was a fetch failure.
                if (!bundle && bundleError) {
                  return (
                    <div style={{ flex:1, display:'flex', alignItems:'center', justifyContent:'center', padding:40, flexDirection:'column', gap:10 }}>
                      <div style={{ fontSize:14, fontWeight:600, color:'#0f172a' }}>Couldn't load trade-off data</div>
                      <div style={{ fontSize:12.5, color:'#5a6585', maxWidth:480, textAlign:'center' }}>
                        {bundleError}
                      </div>
                      <button
                        type="button"
                        onClick={() => window.location.reload()}
                        style={{ marginTop:8, padding:'8px 14px', borderRadius:8, background:'#0f172a', color:'#fff', border:'none', fontSize:13, cursor:'pointer' }}
                      >Refresh</button>
                    </div>
                  );
                }

                return (
                  <TradeoffView
                    flow
                    scorecardSnapshots={list}
                    strategyObjective={bundle?.strategy_objective || 'balanced'}
                    portfolioAnalysis={null}
                    onAsk={() => { /* no-op for now */ }}
                    asking={false}
                    threadId={threadId}
                    buildingPlanId={buildingPlan}
                    onBuildExecutionPlan={(idea) => buildExecutionPlan({
                      source: idea?.snapId || idea?.id,
                      scorecard_id: idea?.snapId || undefined,
                      scenario_id: idea?._snap?.scenario_id || idea?._snap?.scenarioId || undefined,
                    })}
                    onOpenIdeaWorkspace={(idea) => {
                      const ideaId = idea?.snapId || idea?.id;
                      if (ideaId) navigate(`/workspace/${threadId}/${ideaId}`);
                    }}
                  />
                );
              })()}
            </div>
          ) : isExecution ? (
            <JaspenExecutionCanvas
              threadId={threadId}
              scorecardId={execIdeaId}
              bundle={bundle}
              wbs={wbs}
              displayTitle={(() => {
                // The header names the IDEA whose plan is open (?idea=) and
                // NOTHING else — each idea stands on its own. No baseline /
                // scenario fallback: that's exactly the cross-idea leakage we're
                // killing. If we can't resolve the idea, stay generic.
                if (execIdeaSnap) {
                  const fromIdea = _pickMeaningful(
                    execIdeaSnap?.display_overrides?.title,
                    execIdeaSnap?.name, execIdeaSnap?.project_name,
                    execIdeaSnap?.title, execIdeaSnap?.label,
                  );
                  if (fromIdea) return fromIdea;
                }
                // Fall back to the plan's own name, then a neutral label —
                // never another idea's identity.
                return _pickMeaningful(wbs?.name) && wbs?.name !== 'AI Generated Project Plan'
                  ? wbs.name
                  : 'Execution plan';
              })()}
              score={Number(execIdeaSnap?.jaspen_score || execIdeaSnap?.score || 0) || null}
              isWinner={!!execIdeaSnap && String(execIdeaSnap?.id || execIdeaSnap?.analysis_id || '') === String(bundle?.selected_scorecard_id || bundle?.adopted_scenario_id || '')}
              onAskJaspen={(text) => {
                setChatInput(text);
              }}
            />
          ) : (
          <div
            style={{
              maxWidth:980, margin:'0 auto', background:'#fff', borderRadius:14,
              boxShadow:'0 1px 3px rgba(15,23,42,0.06), 0 8px 24px rgba(15,23,42,0.04)',
              padding:'36px 40px',
            }}
          >
            {/* Title — editable */}
            <EditableText
              value={displayTitle}
              onCommit={(v) => setOverride('title', v)}
              style={{ fontSize:24, fontWeight:600, color:'#0f172a', letterSpacing:'-0.01em' }}
            />

            {/* Section grid — 4-column so sections can snap to 25/50/75/100% */}
            <div style={{ display:'grid', gridTemplateColumns:'repeat(4, 1fr)', gap:20, marginTop:28 }}>
              {sectionLayout.map((section, idx) => {
                // Skip sections with no data
                if (section.key === 'executive' &&
                    !rendered?.executive_summary &&
                    rendered?._display_overrides?.executive_summary === undefined) return null;
                if (section.key === 'risks' &&
                    !(Array.isArray(rendered?.top_risks) && rendered.top_risks.length > 0) &&
                    rendered?._display_overrides?.top_risks === undefined) return null;
                if (section.key === 'scenario' && !recommendedScenario &&
                    rendered?._display_overrides?.recommended_scenario === undefined) return null;

                const isCollapsed = section.collapsed;

                const toggleCollapse = () => {
                  setSectionLayout((prev) =>
                    prev.map((s, i) => i === idx ? { ...s, collapsed: !s.collapsed } : s)
                  );
                };

                const toggleSize = () => {
                  setSectionLayout((prev) =>
                    prev.map((s, i) => i === idx ? { ...s, cols: s.cols === 2 ? 1 : 2 } : s)
                  );
                };

                const handleDragStart = (e) => {
                  dragSectionRef.current = idx;
                  e.dataTransfer.effectAllowed = 'move';
                };

                const clearDropIndicator = (el) => {
                  el.style.borderTop = '';
                  el.style.borderLeft = '';
                  el.style.borderRight = '';
                  delete el.dataset.dropAfter;
                };

                const handleDragOver = (e) => {
                  e.preventDefault();
                  const rect = e.currentTarget.getBoundingClientRect();
                  const isAfter = e.clientX > rect.left + rect.width / 2;
                  e.currentTarget.dataset.dropAfter = isAfter ? '1' : '0';
                  if (isAfter) {
                    e.currentTarget.style.borderRight = '2px solid #a0036c';
                    e.currentTarget.style.borderLeft = '';
                  } else {
                    e.currentTarget.style.borderLeft = '2px solid #a0036c';
                    e.currentTarget.style.borderRight = '';
                  }
                  e.currentTarget.style.borderTop = '';
                };

                const handleDragLeave = (e) => {
                  clearDropIndicator(e.currentTarget);
                };

                const handleDrop = (e) => {
                  e.preventDefault();
                  const isAfter = e.currentTarget.dataset.dropAfter === '1';
                  clearDropIndicator(e.currentTarget);
                  const fromIdx = dragSectionRef.current;
                  if (fromIdx === null || fromIdx === idx) return;
                  setSectionLayout((prev) => {
                    const next = [...prev];
                    const [moved] = next.splice(fromIdx, 1);
                    const targetIdx = idx > fromIdx ? idx - 1 : idx;
                    next.splice(isAfter ? targetIdx + 1 : targetIdx, 0, moved);
                    return next;
                  });
                  dragSectionRef.current = null;
                };

                return (
                  <div
                    key={section.key}
                    draggable
                    onDragStart={handleDragStart}
                    onDragOver={handleDragOver}
                    onDragLeave={handleDragLeave}
                    onDrop={handleDrop}
                    style={{
                      gridColumn: `span ${section.cols}`,
                      background: isCollapsed ? '#fafbfc' : '#fff',
                      borderRadius: 8,
                      padding: isCollapsed ? 0 : '12px',
                      transition: 'all 0.15s',
                      boxSizing: 'border-box',
                    }}
                  >
                    {/* Section header bar */}
                    <div style={{
                      display:'flex', alignItems:'center', gap:8,
                      padding:'6px 0', marginBottom: isCollapsed ? 0 : 12,
                      cursor:'default', borderBottom:'1px solid #e6eaf2',
                    }}>
                      {/* Drag handle */}
                      <span style={{ fontSize:14, color:'#cbd5e1', cursor:'grab', userSelect:'none' }}>⠿</span>
                      {/* Label */}
                      <span style={{
                        fontSize:11, fontWeight:600, color:'#64748b',
                        letterSpacing:'0.06em', textTransform:'uppercase', flex:1,
                      }}>
                        {section.label}
                      </span>
                      {/* Lock badge */}
                      {section.locked && (
                        <span style={{
                          padding:'1px 6px', background:'#f1f5f9', borderRadius:6,
                          fontSize:9, color:'#94a3b8',
                        }}>LOCKED</span>
                      )}
                      {/* Grid width picker — 4 segments = 25/50/75/100% */}
                      <div
                        style={{ display:'flex', gap:2, flexShrink:0, alignItems:'center' }}
                        title={`Width: ${section.cols}/4 columns`}
                      >
                        {[1,2,3,4].map((n) => (
                          <button
                            key={n}
                            type="button"
                            onClick={() => setSectionLayout(prev => prev.map((s, i) => i === idx ? { ...s, cols: n } : s))}
                            title={n === 1 ? '¼ width' : n === 2 ? '½ width' : n === 3 ? '¾ width' : 'Full width'}
                            style={{
                              width:9, height:14, borderRadius:2, border:'none', cursor:'pointer', padding:0,
                              background: n <= section.cols ? '#0f172a' : '#e2e8f0',
                              transition:'background 0.1s',
                            }}
                          />
                        ))}
                      </div>
                      {/* Dimensions-specific: inner bar column picker */}
                      {section.key === 'dimensions' && (
                        <div
                          style={{ display:'flex', gap:2, flexShrink:0, alignItems:'center' }}
                          title={`Bars: ${section.dimCols ?? 2} column${(section.dimCols ?? 2) > 1 ? 's' : ''}`}
                        >
                          {[1,2].map((n) => (
                            <button
                              key={n}
                              type="button"
                              onClick={() => setSectionLayout(prev => prev.map((s, i) => i === idx ? { ...s, dimCols: n } : s))}
                              title={n === 1 ? '1-column bars' : '2-column bars'}
                              style={{
                                width:9, height:14, borderRadius:2, border:'none', cursor:'pointer', padding:0,
                                background: n <= (section.dimCols ?? 2) ? '#0f172a' : '#e2e8f0',
                                transition:'background 0.1s',
                              }}
                            />
                          ))}
                        </div>
                      )}
                      {/* Collapse toggle */}
                      <button
                        type="button"
                        onClick={toggleCollapse}
                        title={isCollapsed ? 'Expand' : 'Collapse'}
                        style={{ fontSize:11, color:'#94a3b8', cursor:'pointer', background:'none', border:'none', padding:'2px 4px' }}
                      >
                        {isCollapsed ? '›' : '⌄'}
                      </button>
                    </div>

                    {/* Section content */}
                    <div style={{ display: isCollapsed ? 'none' : 'block' }}>
                      {section.key === 'score' && (
                        <div style={{ display:'flex', alignItems:'center', gap:24 }}>
                          <div style={{ position:'relative', width:96, height:96 }}>
                            <svg width="96" height="96" viewBox="0 0 96 96">
                              <circle cx="48" cy="48" r="36" fill="none" stroke="#e6eaf2" strokeWidth="8" />
                              <circle
                                cx="48" cy="48" r="36" fill="none" stroke={ringColor} strokeWidth="8"
                                strokeDasharray={2 * Math.PI * 36}
                                strokeDashoffset={(1 - score / 100) * 2 * Math.PI * 36}
                                strokeLinecap="round"
                                transform="rotate(-90 48 48)"
                              />
                            </svg>
                            <div style={{ position:'absolute', inset:0, display:'flex', alignItems:'center', justifyContent:'center', fontSize:26, fontWeight:600, color:'#0f172a' }}>
                              {score}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize:11, fontWeight:600, color:ringColor, letterSpacing:'0.06em', textTransform:'uppercase' }}>{category}</div>
                            <div style={{ fontSize:18, fontWeight:600, color:'#0f172a', marginTop:4 }}>Strategy scorecard</div>
                            <div style={{ fontSize:12, color:'#64748b', marginTop:2 }}>Locked · scores reflect Jaspen's analysis. Open chat to rescore.</div>
                          </div>
                        </div>
                      )}

                      {section.key === 'executive' && (
                        <EditableText
                          multiline
                          value={rendered?.executive_summary || ''}
                          onCommit={(v) => setOverride('executive_summary', v)}
                          style={{ fontSize:14, color:'#334155', lineHeight:1.6 }}
                        />
                      )}

                      {section.key === 'dimensions' && (
                        <DimensionBars
                          dims={rendered?.dimensions || {}}
                          cols={section.dimCols ?? 2}
                          dimOrder={section.dimOrder
                            ?? (Array.isArray(rendered?.rubric?.criteria)
                              ? rendered.rubric.criteria.map((c) => c?.key).filter(Boolean)
                              : null)}
                          onReorder={(newOrder) => setSectionLayout(prev =>
                            prev.map((s, i) => i === idx ? { ...s, dimOrder: newOrder } : s)
                          )}
                        />
                      )}

                      {section.key === 'risks' && (
                        // Manually editable — one risk per line. Risks are
                        // qualitative and don't change the score, so they're not
                        // locked. AI edits flow through chat; this is the manual
                        // path. pre-line keeps the line breaks in read mode.
                        <EditableText
                          multiline
                          value={(Array.isArray(rendered?.top_risks) ? rendered.top_risks : [])
                            .map((r) => (typeof r === 'string' ? r : (r?.risk || r?.label || '')))
                            .filter(Boolean)
                            .join('\n')}
                          onCommit={(v) => {
                            const arr = String(v || '')
                              .split('\n').map((s) => s.trim()).filter(Boolean);
                            setOverride('top_risks', arr.length ? arr : null);
                          }}
                          style={{ fontSize:13, color:'#334155', lineHeight:1.65, whiteSpace:'pre-line' }}
                        />
                      )}

                      {section.key === 'scenario' && (
                        <EditableText
                          multiline
                          value={recommendedScenario || ''}
                          onCommit={(v) => setOverride('recommended_scenario', v && v.trim() ? v.trim() : null)}
                          style={{ fontSize:13, color:ringColor, lineHeight:1.65, fontStyle:'italic', whiteSpace:'pre-line' }}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Custom blocks — free-form sections the user (or agent) can add,
                like adding an element in a deck/spreadsheet. Stored in
                display_overrides.custom_blocks; editable / removable here. */}
            {(() => {
              const blocks = Array.isArray(overrides?.custom_blocks) ? overrides.custom_blocks : [];
              const updateBlocks = (next) => setOverride('custom_blocks', next.length ? next : null);
              const accent = ringColor;
              // A small, strategic set of element types — not boiling the ocean.
              const BLOCK_TYPES = [
                { key: 'text', label: 'Text section', hint: 'Heading + paragraph', defaultHeading: 'New section' },
                { key: 'callout', label: 'Callout', hint: 'Highlighted note box', defaultHeading: 'Note' },
                { key: 'quote', label: 'Quote', hint: 'Italic, attributed', defaultHeading: 'Quote' },
              ];
              const addBlock = (type) => {
                const def = BLOCK_TYPES.find((t) => t.key === type) || BLOCK_TYPES[0];
                // Place the new tile in a fresh row below the others.
                const maxY = blocks.reduce((m, b) => Math.max(m, (Number.isFinite(b?.y) ? b.y : 0) + (Number.isFinite(b?.h) ? b.h : 4)), 0);
                updateBlocks([...blocks, { id: `blk_${Date.now()}`, type: def.key, heading: def.defaultHeading, body: '', x: 0, y: maxY, w: 6, h: 4 }]);
              };
              // Map blocks -> grid layout. Migrate legacy `cols` (1..4) to 12-col width.
              const gridLayout = blocks.map((b, i) => {
                const w = Number.isFinite(b?.w) ? b.w : (b?.cols ? Math.min(12, Math.max(2, b.cols * 3)) : 6);
                const h = Number.isFinite(b?.h) ? b.h : 4;
                const x = Number.isFinite(b?.x) ? b.x : 0;
                const y = Number.isFinite(b?.y) ? b.y : i * 4;
                return { i: String(b?.id || `blk_${i}`), x, y, w, h, minW: 2, minH: 2 };
              });
              const onGridLayoutChange = (next) => {
                const byId = {};
                next.forEach((l) => { byId[l.i] = l; });
                let changed = false;
                const updated = blocks.map((b) => {
                  const l = byId[String(b?.id)];
                  if (!l) return b;
                  if (b.x !== l.x || b.y !== l.y || b.w !== l.w || b.h !== l.h) changed = true;
                  return { ...b, x: l.x, y: l.y, w: l.w, h: l.h };
                });
                if (changed) updateBlocks(updated);
              };
              return (
                <div style={{ marginTop:20 }}>
                  {blocks.length > 0 && (
                    <BlockGrid
                      className="jw-block-grid"
                      layout={gridLayout}
                      cols={12}
                      rowHeight={28}
                      margin={[14, 14]}
                      isDraggable
                      isResizable
                      draggableHandle=".blk-drag-handle"
                      resizeHandles={['se']}
                      onLayoutChange={onGridLayoutChange}
                    >
                      {blocks.map((blk, bi) => {
                        const blockType = String(blk?.type || 'text');
                        const baseStyle = { height:'100%', boxSizing:'border-box', borderRadius:10, padding:'10px 12px', display:'flex', flexDirection:'column', overflow:'hidden' };
                        const containerStyle = blockType === 'callout'
                          ? { ...baseStyle, background:`${accent}0d`, border:`1px solid ${accent}33`, borderLeft:`3px solid ${accent}` }
                          : { ...baseStyle, background:'#fff', border:'1px solid #e6eaf2' };
                        const bodyStyle = blockType === 'quote'
                          ? { fontSize:13.5, color:'#334155', lineHeight:1.6, whiteSpace:'pre-line', fontStyle:'italic', borderLeft:'3px solid #e6eaf2', paddingLeft:12, overflow:'auto', flex:1 }
                          : { fontSize:13, color:'#334155', lineHeight:1.6, whiteSpace:'pre-line', overflow:'auto', flex:1 };
                        return (
                          <div key={String(blk?.id || bi)} style={containerStyle}>
                            <div style={{ display:'flex', alignItems:'center', gap:8, marginBottom:6 }}>
                              <span className="blk-drag-handle" style={{ fontSize:14, color:'#cbd5e1', cursor:'grab', userSelect:'none' }} title="Drag to move">⠿</span>
                              <div style={{ flex:1, minWidth:0 }}>
                                <EditableText
                                  value={blk?.heading || ''}
                                  onCommit={(v) => updateBlocks(blocks.map((b, i) => i === bi ? { ...b, heading: v } : b))}
                                  style={{ fontSize:11, fontWeight:600, color: blockType === 'callout' ? accent : '#64748b', letterSpacing:'0.06em', textTransform:'uppercase', display:'block' }}
                                />
                              </div>
                              {confirmDeleteBlockId === (blk?.id || bi) ? (
                                <span style={{ display:'flex', alignItems:'center', gap:6, flexShrink:0 }}>
                                  <span style={{ fontSize:11, color:'#94a3b8' }}>Delete?</span>
                                  <button onClick={() => { updateBlocks(blocks.filter((_, i) => i !== bi)); setConfirmDeleteBlockId(null); }} title="Confirm delete" style={{ border:'none', background:'transparent', color:'#dc2626', cursor:'pointer', fontSize:12, fontWeight:600, padding:2 }}>Yes</button>
                                  <button onClick={() => setConfirmDeleteBlockId(null)} title="Keep" style={{ border:'none', background:'transparent', color:'#64748b', cursor:'pointer', fontSize:12, padding:2 }}>No</button>
                                </span>
                              ) : (
                                <button onClick={() => setConfirmDeleteBlockId(blk?.id || bi)} title="Remove block" onMouseEnter={(e) => { e.currentTarget.style.color = '#94a3b8'; }} onMouseLeave={(e) => { e.currentTarget.style.color = '#cbd5e1'; }} style={{ border:'none', background:'transparent', color:'#cbd5e1', cursor:'pointer', fontSize:14, lineHeight:1, padding:2, flexShrink:0 }}>×</button>
                              )}
                            </div>
                            <EditableText
                              multiline
                              value={blk?.body || ''}
                              onCommit={(v) => updateBlocks(blocks.map((b, i) => i === bi ? { ...b, body: v } : b))}
                              style={bodyStyle}
                            />
                          </div>
                        );
                      })}
                    </BlockGrid>
                  )}
                  <div style={{ position:'relative', marginTop: blocks.length ? 8 : 0 }}>
                    <button
                      onClick={() => setAddBlockMenuOpen((o) => !o)}
                      style={{ border:'1px dashed #c7d2da', background:'#fff', color:'#475569', borderRadius:8, padding:'8px 14px', fontSize:13, cursor:'pointer', fontWeight:500, display:'inline-flex', alignItems:'center', gap:6 }}
                    >+ Add block <span style={{ fontSize:10, opacity:0.7 }}>▾</span></button>
                    {addBlockMenuOpen && (
                      <>
                        <div onClick={() => setAddBlockMenuOpen(false)} style={{ position:'fixed', inset:0, zIndex:40 }} />
                        <div style={{ position:'absolute', top:'calc(100% + 6px)', left:0, zIndex:41, background:'#fff', border:'1px solid #e6eaf2', borderRadius:10, boxShadow:'0 8px 24px rgba(22,31,59,0.12)', minWidth:210, padding:6, display:'flex', flexDirection:'column' }}>
                          {BLOCK_TYPES.map((t) => (
                            <button
                              key={t.key}
                              onClick={() => { addBlock(t.key); setAddBlockMenuOpen(false); }}
                              onMouseEnter={(e) => { e.currentTarget.style.background = '#f5f7fa'; }}
                              onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
                              style={{ textAlign:'left', padding:'8px 10px', border:'none', background:'transparent', borderRadius:6, cursor:'pointer' }}
                            >
                              <div style={{ fontSize:13, color:'#0f172a', fontWeight:500 }}>{t.label}</div>
                              <div style={{ fontSize:11, color:'#94a3b8', marginTop:1 }}>{t.hint}</div>
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              );
            })()}

            {/* Footer hint */}
            <div style={{
              marginTop:32, paddingTop:18, borderTop:'1px solid #e6eaf2',
              fontSize:12, color:'#64748b',
            }}>
              Click any heading, summary, risk, or scenario above to edit, or “+ Add block” to add your own section. Only the score and dimensions stay locked — use the chat to rescore those.
            </div>
          </div>
          )}
        </div>
      </main>
    </div>
  );
}

// ── EditableText: click to inline-edit. onCommit fires on blur or Enter. ────
function EditableText({ value, onCommit, multiline = false, style }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');

  useEffect(() => { setDraft(value || ''); }, [value]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onCommit?.(draft);
  };

  if (!editing) {
    return (
      <div
        onClick={() => setEditing(true)}
        title="Click to edit"
        style={{
          ...style,
          cursor:'text', borderRadius:6, padding:'2px 4px', margin:'-2px -4px',
          transition:'background 120ms',
        }}
        onMouseEnter={(e) => { e.currentTarget.style.background = '#f7f8fa'; }}
        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; }}
      >
        {value || <span style={{ color:'#94a3b8' }}>Click to add…</span>}
      </div>
    );
  }

  if (multiline) {
    return (
      <textarea
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Escape') { setDraft(value || ''); setEditing(false); } }}
        style={{
          ...style,
          width:'100%', minHeight:90, border:'1px solid #c7d2da', borderRadius:6,
          padding:'8px 10px', resize:'vertical', fontFamily:'inherit',
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
      style={{
        ...style,
        width:'100%', border:'1px solid #c7d2da', borderRadius:6, padding:'4px 8px',
        fontFamily:'inherit',
      }}
    />
  );
}

// ── DimensionBars: read-only score bars per dimension. ──────────────────────
// Labels and colors match the chat scorecard's renderScorecardCard so the
// workspace canvas reads identically. Risk dimensions show in orange; all
// other dimensions show in navy.
const _DIMENSION_LABELS = {
  strategic_alignment: 'Strategic fit',
  financial_viability: 'Cost efficiency',
  execution_readiness: 'Time-to-value',
  risk_profile: 'Execution risk',
  market_opportunity: 'Market Opportunity',
  evidence_quality: 'Evidence Quality',
};
const _DIMENSION_ORDER = [
  'strategic_alignment',
  'financial_viability',
  'execution_readiness',
  'risk_profile',
  'market_opportunity',
  'evidence_quality',
];
const _RISK_DIMENSIONS = new Set(['risk_profile']);

function DimensionBars({ dims, cols = 2, dimOrder, onReorder }) {
  const dragDimRef = useRef(null);

  if (!dims || typeof dims !== 'object') return null;
  let ordered = _DIMENSION_ORDER
    .map((key) => ({ key, dim: dims[key] }))
    .filter(({ dim }) => dim && typeof dim === 'object');
  for (const [key, dim] of Object.entries(dims)) {
    if (!_DIMENSION_LABELS[key] && dim && typeof dim === 'object') {
      ordered.push({ key, dim });
    }
  }
  if (ordered.length === 0) return null;

  if (dimOrder && dimOrder.length > 0) {
    const map = new Map(ordered.map((d) => [d.key, d]));
    const reordered = dimOrder.map((k) => map.get(k)).filter(Boolean);
    for (const d of ordered) {
      if (!dimOrder.includes(d.key)) reordered.push(d);
    }
    ordered = reordered;
  }

  return (
    <div style={{ display:'grid', gridTemplateColumns:`repeat(${cols}, 1fr)`, gap:'14px 32px' }}>
      {ordered.map(({ key, dim }, dimIdx) => {
        const score = Number(dim?.score || 0);
        // Prefer the payload's own label (custom rubric); fall back to the built-in map.
        const label = dim?.label
          || _DIMENSION_LABELS[key]
          || key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
        // Custom rubric criteria carry their own is_risk flag; otherwise use the built-in set.
        const isRisk = (dim && typeof dim.is_risk === 'boolean') ? dim.is_risk : _RISK_DIMENSIONS.has(key);
        const barColor = isRisk ? COLOR_RISK_ORANGE : COLOR_NAVY;

        const handleDimDragStart = (e) => {
          dragDimRef.current = dimIdx;
          e.dataTransfer.effectAllowed = 'move';
          e.stopPropagation();
        };
        const handleDimDragOver = (e) => {
          if (!onReorder) return;
          e.preventDefault();
          e.stopPropagation();
          const rect = e.currentTarget.getBoundingClientRect();
          const isAfter = e.clientX > rect.left + rect.width / 2;
          e.currentTarget.dataset.dropAfter = isAfter ? '1' : '0';
          e.currentTarget.style.borderRight = isAfter ? '2px solid #a0036c' : '';
          e.currentTarget.style.borderLeft = isAfter ? '' : '2px solid #a0036c';
        };
        const handleDimDragLeave = (e) => {
          e.currentTarget.style.borderLeft = '';
          e.currentTarget.style.borderRight = '';
          delete e.currentTarget.dataset.dropAfter;
        };
        const handleDimDrop = (e) => {
          if (!onReorder) return;
          e.preventDefault();
          e.stopPropagation();
          const isAfter = e.currentTarget.dataset.dropAfter === '1';
          e.currentTarget.style.borderLeft = '';
          e.currentTarget.style.borderRight = '';
          delete e.currentTarget.dataset.dropAfter;
          const fromIdx = dragDimRef.current;
          if (fromIdx === null || fromIdx === dimIdx) return;
          const keys = ordered.map((d) => d.key);
          const [moved] = keys.splice(fromIdx, 1);
          const targetIdx = dimIdx > fromIdx ? dimIdx - 1 : dimIdx;
          keys.splice(isAfter ? targetIdx + 1 : targetIdx, 0, moved);
          onReorder(keys);
          dragDimRef.current = null;
        };

        return (
          <div
            key={key}
            draggable={!!onReorder}
            onDragStart={handleDimDragStart}
            onDragOver={handleDimDragOver}
            onDragLeave={handleDimDragLeave}
            onDrop={handleDimDrop}
            style={{ cursor: onReorder ? 'grab' : 'default', padding:'2px 0' }}
          >
            <div style={{ display:'flex', justifyContent:'space-between', fontSize:13, color:'#0f172a', marginBottom:6 }}>
              <span>{label}</span>
              <span style={{ fontFamily:'JetBrains Mono, monospace', fontSize:12, color:'#475569' }}>
                {(score / 10).toFixed(1)}<span style={{ color:'#94a3b8' }}>/10</span>
              </span>
            </div>
            <div style={{ height:6, background:'#eef2f6', borderRadius:3, overflow:'hidden' }}>
              <div style={{ height:'100%', width:`${score}%`, background:barColor, borderRadius:3 }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}
