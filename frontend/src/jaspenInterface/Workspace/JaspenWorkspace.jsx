// ============================================================================
// File: frontend/src/Market/MarketIQ/workspace/MarketIQWorkspace.jsx
// Purpose: Keep original drawer behavior, FIX readiness "snap" issue,
//          and show tabs AFTER Finish & Analyze.
// ============================================================================

import React, { useEffect, useRef, useState, useMemo, useReducer, useCallback } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { API_BASE } from '../../config/apiBase';
import { useChatCommands, parseUIActions, ChatActionTypes } from "../../shared/hooks/useChatCommands"
import { useToast, ToastContainer } from '../../shared/components/Toast';
import { useAuth } from 'shared/auth/AuthContext';

import { FontAwesomeIcon } from '@fortawesome/react-fontawesome';
import {
  faQuestionCircle,
  faPaperPlane, faSpinner, faTimes, faBars, faCheck, faExclamationTriangle,
  faChartLine, faTrash, faPlus, faMinus, faMicrophone,
  faBolt, faLayerGroup, faPlay, faListCheck, faArrowUpRightFromSquare, faGaugeHigh, faClockRotateLeft, faPaperclip, faArrowUp,
  faDownload, faChevronDown, faChevronUp
} from '@fortawesome/free-solid-svg-icons';
import {
  MonitorCheck, MessageCircleQuestion,
  Sigma, Plus as LucidePlus, BarChart3
} from 'lucide-react';

// Data / storage
import { MarketIQ, storage } from './JaspenClient';

// Tab components
import ScoreDashboard   from './ScoreDashboard';
import ScenarioModeler  from './ScenarioModeler';
import ComparisonView   from './ComparisonView';
import ThreadEditModal from '../components/ThreadEditModal';

// Styles - Single source of truth
import "./JaspenWorkspace.css";

// === Header Icon Helpers =====================================================
const PM_VARIANT  = "monitor-check";
const LSS_VARIANT = "chart-scatter";

// ============================================================================
// Readiness Normalization Helpers (Backend Contract Compliance)
// ============================================================================

/**
 * Normalize readiness value to standard object shape
 * Per backend contract: readiness can be int, float, string, or object
 * Matches sessions.py normalization behavior
 */
function normalizeReadiness(value) {
  if (value && typeof value === 'object') {
    const percent = Math.max(0, Math.min(100, Math.round(Number(value.percent) || 0)));
    const categories = Array.isArray(value.categories) ? value.categories : [];
    const updated_at = value.updated_at || null;
    return { percent, categories, updated_at };
  }
  
  // Primitive value (int/float/string)
  const pct = Math.max(0, Math.min(100, Math.round(Number(value) || 0)));
  return { percent: pct, categories: [], updated_at: null };
}

/**
 * Clamp percentage to valid range [0, 100]
 */
function clampPercent(p) {
  return Math.max(0, Math.min(100, Math.round(Number(p) || 0)));
}

function isContextSyncMessage(text) {
  return String(text || '').trim().toLowerCase() === '[context-sync]';
}

function toUiMessages(history = []) {
  return (Array.isArray(history) ? history : [])
    .map((msg) => ({
      role: msg?.role === 'user' ? 'user' : 'ai',
      text: (msg?.content || msg?.text || '').trim(),
    }))
    .filter((m) => m.text.length > 0 && !isContextSyncMessage(m.text));
}

function deriveIdeaTitle({ result = null, messages = [], fallback = 'Untitled Idea' } = {}) {
  const projectName = String(
    result?.project_name ||
    result?.name ||
    result?.title ||
    result?.compat?.title ||
    ''
  ).trim();
  if (projectName) return projectName;

  const firstUserIdea = (Array.isArray(messages) ? messages : [])
    .find((m) => m?.role === 'user' && String(m?.text || '').trim().length > 0);

  if (firstUserIdea?.text) {
    return String(firstUserIdea.text).trim().slice(0, 72);
  }

  return fallback;
}

// ============================================================================
// Sidebar State Reducer
// ============================================================================
const sidebarReducer = (state, action) => {
  switch (action.type) {
    case 'OPEN_HISTORY':
      return { ...state, history: true, readiness: false, settings: false, userDismissedReadiness: true };
    case 'OPEN_READINESS':
      return { ...state, history: false, readiness: true, settings: false };
    case 'OPEN_SETTINGS':
      return { ...state, history: false, readiness: false, settings: true };
    case 'CLOSE_HISTORY':
      return { ...state, history: false };
    case 'CLOSE_READINESS':
      return { ...state, readiness: false, userDismissedReadiness: true };
    case 'CLOSE_SETTINGS':
      return { ...state, settings: false };
    case 'CLOSE_ALL':
      return { ...state, history: false, readiness: false, settings: false };
    case 'TOGGLE_HISTORY':
      return { ...state, history: !state.history, readiness: false, settings: false };
    case 'TOGGLE_READINESS':
      return { ...state, history: false, readiness: !state.readiness, settings: false };
    case 'TOGGLE_SETTINGS':
      return { ...state, history: false, readiness: false, settings: !state.settings };
    case 'NEW_SESSION':
      return { ...state, userDismissedReadiness: false };
    default:
      return state;
  }
};

// --- Normalize any session/result into today's scorecard shape ---
function normalizeAnalysis(raw = {}) {
  const compat = raw.compat || {};
  const comps  = raw.component_scores || compat.components || {};
  const fin    = raw.financial_impact || compat.financials || {};

  const toInt = (v) => {
    const n = parseInt(Number(v), 10);
    return Number.isFinite(n) ? n : 0;
  };

  const score = toInt(raw.market_iq_score ?? raw.score ?? compat.score);
  const score_category =
    raw.score_category ||
    (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk');

return {
  ...raw,  // Keep all original fields
  market_iq_score: score,
  score_category,
  component_scores: {
    financial_health:       toInt(comps.financial_health       ?? comps.financialHealth       ?? comps.financial   ?? comps.economics),
    operational_efficiency: toInt(comps.operational_efficiency ?? comps.operationalEfficiency ?? comps.execution   ?? comps.operations),
    market_position:        toInt(comps.market_position        ?? comps.marketPosition        ?? comps.market      ?? comps.strategy),
    execution_readiness:    toInt(comps.execution_readiness    ?? comps.executionReadiness    ?? comps.team        ?? comps.readiness),
  },
  financial_impact: {
    ebitda_at_risk:   fin.ebitda_at_risk   ?? fin.ebitdaAtRisk   ?? null,
    potential_loss:   fin.potential_loss   ?? fin.potentialLoss  ?? null,
    roi_opportunity:  fin.roi_opportunity  ?? fin.roiOpportunity ?? null,
    projected_ebitda: fin.projected_ebitda ?? fin.projectedEbitda?? null,
  },
  project_name: raw.project_name || compat.title || raw.title || 'Untitled Idea',
  risks: Array.isArray(raw.risks) ? raw.risks : (raw.top_risks || []),
  // Explicitly preserve detailed sections
  decision_framework: raw.decision_framework || raw.strategic_decision_framework || null,
  investment_analysis: raw.investment_analysis || null,
  npv_irr_analysis: raw.npv_irr_analysis || null,
  valuation: raw.valuation || null,
  before_after_financials: raw.before_after_financials || null,
};
}
export default function MarketIQWorkspace() {
  // View states: intake | summary | scenario | comparison | chat
  const [view, setView] = useState('intake');
  const [activeTab, setActiveTab] = useState('summary');

  const { user, logout, setUser } = useAuth();

  // Imperative control for scenario modeling (used by interactive chat actions)
  const scenarioModelerRef = useRef(null);

  const [sidebarState, dispatchSidebar] = useReducer(sidebarReducer, {
    history: false,
    readiness: false,
    settings: true,
    userDismissedReadiness: false
  });
  const didAutoOpenSettingsRef = useRef(false);

  useEffect(() => {
    if (didAutoOpenSettingsRef.current) return;
    didAutoOpenSettingsRef.current = true;
    dispatchSidebar({ type: 'OPEN_SETTINGS' });
  }, []);

  const [sessionId, setSessionId] = useState(null);
  const [currentSessionId, setCurrentSessionId] = useState(null);
  const [sessionsLoading, setSessionsLoading] = useState(true);
  const [messages, setMessages] = useState([]);

  // Readiness core state - SINGLE SOURCE OF TRUTH
  const [readinessAudit, setReadinessAudit] = useState(null); // ONLY source: GET /api/readiness/audit (authoritative)
  const [collectedData, setCollectedData] = useState({});
  const READINESS_CIRC = 2 * Math.PI * 52; // r=52 -> circumference ~326.7

  const [input, setInput] = useState('');
  const [pendingFiles, setPendingFiles] = useState([]);

  const [busy, setBusy] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const [error, setError] = useState(null);
  const recognitionRef = useRef(null);

  const [analysisResult, setAnalysisResult] = useState(null);
  // Scenario results kept at the Workspace level (so Score tab can switch)
const [resultA, setResultA] = useState(null);
const [resultB, setResultB] = useState(null);
const [resultC, setResultC] = useState(null);
// Backend truth for macro categories + weights + version
const [readinessSpec, setReadinessSpec] = useState(null);   // full spec payload
const [specMap, setSpecMap] = useState({});                 // key -> {label, weight}
const [readinessSource, setReadinessSource] = useState(null); // "ml" or "heuristic"
const [readinessVersion, setReadinessVersion] = useState(null);

// Variant selector (Baseline, Scenario A/B/C)
const [scoreVariants, setScoreVariants] = useState([]);
const [selectedVariantId, setSelectedVariantId] = useState('baseline');
// Keep the list of selectable score variants in sync
useEffect(() => {
  const opts = [
    analysisResult ? { id: 'baseline',  label: 'Baseline',   result: analysisResult } : null,
    resultA        ? { id: 'scenarioA', label: 'Scenario A', result: resultA }        : null,
    resultB        ? { id: 'scenarioB', label: 'Scenario B', result: resultB }        : null,
    resultC        ? { id: 'scenarioC', label: 'Scenario C', result: resultC }        : null,
  ].filter(Boolean);

  setScoreVariants(opts);

  // if current selection vanished (e.g., cleared a scenario), default to Baseline
  const stillExists = opts.some(o => o.id === selectedVariantId);
  if (!stillExists) setSelectedVariantId('baseline');
}, [analysisResult, resultA, resultB, resultC]); 
const selectedVariant = useMemo(() => {
  return (
    scoreVariants.find(v => v.id === selectedVariantId)?.result ||
    analysisResult
  );
}, [scoreVariants, selectedVariantId, analysisResult]);

  const [analysisHistory, setAnalysisHistory] = useState([]);
  const [clearingHistory, setClearingHistory] = useState(false);
  const [savedScenarios, setSavedScenarios] = useState([]);
  const [helpOpen, setHelpOpen] = useState(false);
  const [helpMessages, setHelpMessages] = useState([]);
const [helpInput, setHelpInput] = useState('');
const [helpLoading, setHelpLoading] = useState(false);
// Score view dropdown state (baseline + up to 3 scenarios)
const [scenarioOptions, setScenarioOptions] = useState([]);
const [activeScenarioId, setActiveScenarioId] = useState('baseline');
const [scenarioDrawerView, setScenarioDrawerView] = useState('assistant');
  const [scenarioLevers, setScenarioLevers] = useState([]);
  const [threadEditOpen, setThreadEditOpen] = useState(false);
  const [bundleCurrentScorecard, setBundleCurrentScorecard] = useState(null);
  const [bundleBaselineScorecard, setBundleBaselineScorecard] = useState(null);
  const hasHistory = analysisHistory.length > 0;

  // PROMPT ALIGNMENT: Scorecard snapshots (baseline + adopted scenarios)
  const [scorecardSnapshots, setScorecardSnapshots] = useState([]);
  const [selectedScorecardId, setSelectedScorecardId] = useState(null);
  const [baselineScorecardId, setBaselineScorecardId] = useState(null);
  // Ensure we always have a baseline scorecard id + snapshot once analysisResult exists
  useEffect(() => {
    if (!analysisResult) return;

    const baseId = analysisResult.analysis_id || analysisResult.id || sessionId;
    if (!baseId) return;

    // If backend provided snapshots, hydrate them once
    const persistedSnaps = Array.isArray(analysisResult?.scorecard_snapshots)
      ? analysisResult.scorecard_snapshots
      : null;

    setBaselineScorecardId((prev) => prev || baseId);

    setScorecardSnapshots((prev) => {
      if (Array.isArray(prev) && prev.length > 0) return prev;

      if (persistedSnaps && persistedSnaps.length > 0) {
        return persistedSnaps;
      }

      return [
        {
          ...analysisResult,
          id: baseId,
          label: 'Baseline',
          isBaseline: true,
          createdAt: Date.now(),
        },
      ];
    });

    // Select something sensible on load:
    // - if backend has snapshots and previously selected is missing, select baseline
    setSelectedScorecardId((prev) => {
      if (prev) return prev;
      if (persistedSnaps?.length) {
        const baseline = persistedSnaps.find(s => s.isBaseline) || persistedSnaps[0];
        return baseline?.id || baseId;
      }
      return baseId;
    });
  }, [analysisResult, sessionId]);

  // Restore selected scorecard on refresh (if backend provided it)
  useEffect(() => {
    if (!analysisResult) return;
    if (analysisResult?.selected_scorecard_id && !selectedScorecardId) {
      setSelectedScorecardId(analysisResult.selected_scorecard_id);
    }
  }, [analysisResult, selectedScorecardId]);

// ============================================================
// Active scorecard = what the UI should display right now
// Priority:
// 1) selectedScorecardId (edited snapshot / adopted snapshot)
// 2) selectedVariant (baseline vs scenario A/B/C)
// 3) analysisResult fallback
// ============================================================
const activeScorecard = useMemo(() => {
  const id = selectedScorecardId;
  if (id && Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0) {
    const snap = scorecardSnapshots.find(s => s.id === id);
    if (snap) return snap;
  }
  return selectedVariant || analysisResult;
}, [selectedScorecardId, scorecardSnapshots, selectedVariant, analysisResult]);

// Preserve the original/baseline analysis result for quick switching
const baselineRef = useRef(null);
  // GOAL B: Track which sessionIds have had their scorecard hydrated
  const hydratedScorecardRef = useRef(new Set());

  // Pull messages, latest analysis id, and saved scenarios from backend
const refreshBundle = async (tid) => {
  if (!tid) return;
  try {
    const bundle = await MarketIQ.getThreadBundle(tid, { msg_limit: 50, scn_limit: 50 });

    // scenarios -> normalize to local shape used by ComparisonView / list
    const serverScenarios = Array.isArray(bundle.scenarios) ? bundle.scenarios : [];
    const normalized = serverScenarios.map((s) => ({
      id: s.scenario_id,
      label: s.label || 'Scenario',
      values: s.deltas || {},
      result: s.result || null,
      timestamp: new Date(s.created_at || Date.now()).getTime(),
    }));

    setSavedScenarios(normalized);
    const bundleLevers = Array.isArray(bundle?.scenario_levers) ? bundle.scenario_levers : [];
    if (bundleLevers.length > 0) {
      setScenarioLevers(bundleLevers);
    } else if (bundle?.current_scorecard?.compat) {
      const fallbackLevers = Object.entries(bundle.current_scorecard.compat)
        .filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
        .map(([key, value]) => ({
          key,
          label: key.replace(/_/g, ' '),
          type: 'number',
          current: value,
        }));
      setScenarioLevers(fallbackLevers);
    } else if (bundle?.baseline_scorecard?.compat) {
      const fallbackLevers = Object.entries(bundle.baseline_scorecard.compat)
        .filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
        .map(([key, value]) => ({
          key,
          label: key.replace(/_/g, ' '),
          type: 'number',
          current: value,
        }));
      setScenarioLevers(fallbackLevers);
    } else if (analysisResult?.compat || analysisResult?.inputs) {
      const source = analysisResult?.compat || analysisResult?.inputs || {};
      const fallbackLevers = Object.entries(source)
        .filter(([, v]) => typeof v === 'number' && Number.isFinite(v))
        .map(([key, value]) => ({
          key,
          label: key.replace(/_/g, ' '),
          type: 'number',
          current: value,
        }));
      setScenarioLevers(fallbackLevers);
    } else {
      setScenarioLevers([]);
    }

    // Hydrate scorecard snapshots from bundle (current + scenario scorecards)
    const bundleSnapshots = [];
    const currentScorecard = bundle?.current_scorecard || null;
    const baselineScorecard = bundle?.baseline_scorecard || null;
    setBundleCurrentScorecard(currentScorecard);
    setBundleBaselineScorecard(baselineScorecard);
    if (currentScorecard && typeof currentScorecard === 'object') {
      bundleSnapshots.push({
        ...currentScorecard,
        id: currentScorecard.analysis_id || currentScorecard.id || currentScorecard.analysisId || `current_${tid}`,
        label: currentScorecard.label || currentScorecard.project_name || 'Current',
        isBaseline: Boolean(currentScorecard.isBaseline),
        createdAt: Date.now(),
      });
    }

    const scenarioScorecards = serverScenarios
      .map((s) => s?.scorecard || s?.analysis_result || s?.result || null)
      .filter((s) => s && typeof s === 'object');

    scenarioScorecards.forEach((sc, idx) => {
      bundleSnapshots.push({
        ...sc,
        id: sc.analysis_id || sc.id || sc.analysisId || `scenario_${idx}_${tid}`,
        label: sc.label || sc.project_name || `Scenario ${idx + 1}`,
        isBaseline: false,
        createdAt: Date.now(),
      });
    });

    if (bundleSnapshots.length > 0) {
      setScorecardSnapshots((prev) => {
        const existing = Array.isArray(prev) ? prev : [];
        const merged = [...existing];
        bundleSnapshots.forEach((snap) => {
          if (!merged.find((s) => s.id === snap.id)) merged.push(snap);
        });
        return merged;
      });
    }

    if (currentScorecard) {
      const currentId = currentScorecard.analysis_id || currentScorecard.id || currentScorecard.analysisId;
      const baselineId = baselineScorecard?.analysis_id || baselineScorecard?.id || baselineScorecard?.analysisId;
      if (currentId) setSelectedScorecardId(currentId);

      if (currentId && baselineId && currentId !== baselineId) {
        const adoptedSnapshot = {
          ...currentScorecard,
          id: currentId,
          label: currentScorecard.label || 'Adopted Scenario',
          isBaseline: false,
          adoptedAt: Date.now(),
        };

        setScorecardSnapshots(prev => {
          const exists = prev.find(s => s.id === currentId);
          if (exists) return prev;
          return [...prev, adoptedSnapshot];
        });
      }
    }
    const bundleMessages = toUiMessages(
      (Array.isArray(bundle?.messages) ? bundle.messages : []).map((m) => ({
        role: m?.role || (m?.sender === 'user' ? 'user' : 'assistant'),
        content: m?.content || m?.text || m?.message || '',
      }))
    );
    if ((messages?.length || 0) === 0 && bundleMessages.length > 0) {
      setMessages(bundleMessages);
    }
  } catch (e) {
    console.debug('[refreshBundle] skipped', e);
  }
};

  const authFetch = (url, options = {}) => {
    const apiBase = API_BASE;
    const fullUrl = url.startsWith('http') ? url : `${apiBase}${url}`;
    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    const headers = {
      ...(options.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
    return fetch(fullUrl, { credentials: 'include', ...options, headers });
  };

  const navigate = useNavigate();

  // User menu helpers
  const getInitials = (name) => {
    if (!name) return 'U';
    const parts = name.split(' ');
    if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase();
    return name.substring(0, 2).toUpperCase();
  };
  const getUserStorageKeys = (u) => {
    const keys = [];
    if (u?.id) keys.push(`jaspen_display_name_id_${u.id}`);
    if (u?.email) keys.push(`jaspen_display_name_email_${String(u.email).toLowerCase()}`);
    keys.push('jaspen_display_name_last');
    return keys;
  };
  const [displayName, setDisplayName] = useState('');
  const [nameInput, setNameInput] = useState('');
  const [nameModalOpen, setNameModalOpen] = useState(false);
  const [billingStatus, setBillingStatus] = useState(null);
  const [billingCatalog, setBillingCatalog] = useState({ plans: {}, overage_packs: {} });
  const [billingLoading, setBillingLoading] = useState(true);
  const [billingMessage, setBillingMessage] = useState('');
  const [billingActionLoading, setBillingActionLoading] = useState('');
  const [billingModalOpen, setBillingModalOpen] = useState(false);
  const [accountQuickMenuOpen, setAccountQuickMenuOpen] = useState(false);
  const [knowledgeMenuOpen, setKnowledgeMenuOpen] = useState(false);
  const accountMenuRef = useRef(null);
  const savedEmail = (() => {
    try { return localStorage.getItem('jaspen_last_email'); } catch { return null; }
  })();
  const userInitials = getInitials(displayName || user?.name || user?.email || savedEmail || 'User');
  const userName = displayName || user?.name || user?.email?.split('@')[0] || savedEmail?.split?.('@')[0] || 'User';
  const userEmail = user?.email || savedEmail || 'user@example.com';
  const [welcomeNow, setWelcomeNow] = useState(() => new Date());
  const planOrder = ['free', 'essential', 'team', 'enterprise'];
  const planRank = { free: 0, essential: 1, team: 2, enterprise: 3 };
  const plans = billingCatalog?.plans || {};
  const currentPlanKey = String(billingStatus?.plan_key || 'free').toLowerCase();
  const currentPlanLabel = plans[currentPlanKey]?.label || (currentPlanKey[0]?.toUpperCase() + currentPlanKey.slice(1));
  const monthlyCreditLimit = billingStatus?.monthly_credit_limit;
  const creditsRemaining = billingStatus?.credits_remaining;
  const creditsBadge = creditsRemaining == null ? 'Contracted' : Number(creditsRemaining || 0).toLocaleString();

  const getAuthToken = useCallback(
    () => localStorage.getItem('access_token') || localStorage.getItem('token'),
    []
  );
  const preferredFirstName = useMemo(() => {
    const source = (displayName || userName || '').trim();
    if (!source) return 'there';
    return source.split(/\s+/)[0];
  }, [displayName, userName]);
  const greetingPrefix = useMemo(() => {
    const hour = welcomeNow.getHours();
    if (hour < 12) return 'Good morning';
    if (hour < 17) return 'Good afternoon';
    return 'Good evening';
  }, [welcomeNow]);
  const dynamicPrompt = useMemo(() => {
    const prompts = [
      'Ready to build momentum?',
      "Let's make progress.",
      "Let's move this forward.",
      'Ready to get something done?',
      "Let's turn ideas into action."
    ];
    const seed = `${preferredFirstName}-${welcomeNow.getFullYear()}-${welcomeNow.getMonth()}-${welcomeNow.getDate()}`;
    const hash = [...seed].reduce((acc, ch) => acc + ch.charCodeAt(0), 0);
    return prompts[hash % prompts.length];
  }, [preferredFirstName, welcomeNow]);
  const welcomeHeading = `${greetingPrefix}, ${preferredFirstName}. ${dynamicPrompt}`;

  useEffect(() => {
    if (!user) return;
    const keys = getUserStorageKeys(user);
    const saved = (() => {
      try {
        return keys.map((k) => localStorage.getItem(k)).find(Boolean) || null;
      } catch {
        return null;
      }
    })();
    const fallback = user?.name || user?.email?.split('@')[0] || '';
    const initial = saved || fallback;
    setDisplayName(saved || '');
    setNameInput(initial);
    if (!saved) setNameModalOpen(true);
    try {
      if (user?.email) localStorage.setItem('jaspen_last_email', user.email);
    } catch {}
  }, [user]);

  useEffect(() => {
    const timer = window.setInterval(() => setWelcomeNow(new Date()), 60000);
    return () => window.clearInterval(timer);
  }, []);

  const persistDisplayName = (value) => {
    const trimmed = String(value || '').trim();
    if (!trimmed) return;
    try {
      const keys = getUserStorageKeys(user);
      keys.forEach((k) => localStorage.setItem(k, trimmed));
    } catch {}
    setDisplayName(trimmed);
    setUser?.((prev) => prev ? { ...prev, name: trimmed } : prev);
  };

  const loadBilling = useCallback(async () => {
    const token = getAuthToken();
    if (!token) {
      setBillingLoading(false);
      return;
    }
    setBillingLoading(true);
    try {
      const [statusRes, catalogRes] = await Promise.all([
        fetch(`${API_BASE}/api/billing/status`, {
          headers: { Authorization: `Bearer ${token}` },
          credentials: 'include'
        }),
        fetch(`${API_BASE}/api/billing/catalog`, { credentials: 'include' })
      ]);
      const statusData = await statusRes.json().catch(() => ({}));
      const catalogData = await catalogRes.json().catch(() => ({}));
      if (!statusRes.ok) {
        throw new Error(statusData?.msg || 'Unable to load plan details.');
      }
      setBillingStatus(statusData || null);
      setBillingCatalog(catalogData || { plans: {}, overage_packs: {} });
      setBillingMessage('');
    } catch (error) {
      setBillingMessage(error.message || 'Unable to load plan details.');
    } finally {
      setBillingLoading(false);
    }
  }, [getAuthToken]);

  useEffect(() => {
    loadBilling();
  }, [loadBilling, user?.id, user?.email]);

  useEffect(() => {
    if (!sidebarState.settings) {
      setAccountQuickMenuOpen(false);
      setKnowledgeMenuOpen(false);
    }
  }, [sidebarState.settings]);

  useEffect(() => {
    if (!accountQuickMenuOpen) return;
    const onPointerDown = (event) => {
      if (!accountMenuRef.current) return;
      if (!accountMenuRef.current.contains(event.target)) {
        setAccountQuickMenuOpen(false);
        setKnowledgeMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', onPointerDown);
    return () => document.removeEventListener('mousedown', onPointerDown);
  }, [accountQuickMenuOpen]);

  const startPlanChange = async (planKey) => {
    const token = getAuthToken();
    if (!token) {
      navigate('/?auth=1');
      return;
    }
    setBillingActionLoading(planKey);
    setBillingMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-checkout-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        credentials: 'include',
        body: JSON.stringify({ plan_key: planKey }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(data?.msg || 'Unable to start plan change.');
      }
      if (data?.url) {
        window.location.href = data.url;
        return;
      }
      await loadBilling();
    } catch (error) {
      setBillingMessage(error.message || 'Unable to start plan change.');
    } finally {
      setBillingActionLoading('');
    }
  };

  const openBillingPortal = async () => {
    const token = getAuthToken();
    if (!token) {
      navigate('/?auth=1');
      return;
    }
    setBillingActionLoading('portal');
    setBillingMessage('');
    try {
      const response = await fetch(`${API_BASE}/api/billing/create-portal-session`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${token}`,
        },
        credentials: 'include',
        body: JSON.stringify({ return_url: `${window.location.origin}/account` }),
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.url) {
        throw new Error(data?.msg || 'Unable to open billing portal.');
      }
      window.location.href = data.url;
    } catch (error) {
      setBillingMessage(error.message || 'Unable to open billing portal.');
    } finally {
      setBillingActionLoading('');
    }
  };

  const renderNameModal = () => {
    if (!nameModalOpen) return null;
    return (
      <div className="jas-name-modal-backdrop" role="presentation">
        <div className="jas-name-modal" role="dialog" aria-modal="true" aria-label="Choose your name">
          <h3>What should I call you?</h3>
          <p>We can use this across Jaspen. You can change it anytime in Settings.</p>
          <input
            className="jas-name-input"
            value={nameInput}
            onChange={(e) => setNameInput(e.target.value)}
            placeholder="Your name"
            autoFocus
          />
          <div className="jas-name-actions">
            <button
              type="button"
              className="jas-name-save"
              onClick={() => {
                const trimmed = nameInput.trim();
                if (!trimmed) return;
                persistDisplayName(trimmed);
                setNameModalOpen(false);
              }}
              disabled={!nameInput.trim()}
            >
              Save
            </button>
          </div>
        </div>
      </div>
    );
  };

  const renderBillingModal = () => {
    if (!billingModalOpen) return null;
    return (
      <div className="jas-modal-backdrop" role="presentation" onClick={() => setBillingModalOpen(false)}>
        <div className="jas-account-modal" role="dialog" aria-modal="true" aria-label="Account and billing" onClick={(e) => e.stopPropagation()}>
          <div className="jas-account-modal-header">
            <h3>Account and billing</h3>
            <button type="button" className="jas-account-modal-close" onClick={() => setBillingModalOpen(false)} aria-label="Close">
              <FontAwesomeIcon icon={faTimes} />
            </button>
          </div>

          <div className="jas-account-summary-grid">
            <article className="jas-account-summary-card">
              <p className="label">Current plan</p>
              <p className="value">{currentPlanLabel}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Credits remaining</p>
              <p className="value">{creditsBadge}</p>
            </article>
            <article className="jas-account-summary-card">
              <p className="label">Monthly limit</p>
              <p className="value">
                {monthlyCreditLimit == null ? 'Contracted' : Number(monthlyCreditLimit).toLocaleString()}
              </p>
            </article>
          </div>

          <div className="jas-account-plan-grid">
            {planOrder.map((key) => {
              const plan = plans[key];
              if (!plan) return null;
              const isCurrent = key === currentPlanKey;
              const isSalesOnly = !!plan.sales_only;
              return (
                <article className={`jas-account-plan-card ${isCurrent ? 'is-current' : ''}`} key={key}>
                  <h4>{plan.label}</h4>
                  <p className="price">
                    {Number.isFinite(plan.monthly_price_usd)
                      ? (plan.monthly_price_usd === 0 ? '$0/mo' : `$${plan.monthly_price_usd}/mo`)
                      : 'Contact sales'}
                  </p>
                  <p className="detail">
                    {plan.monthly_credits == null
                      ? 'Contracted pooled credits'
                      : `${Number(plan.monthly_credits).toLocaleString()} credits/month`}
                  </p>
                  {isCurrent ? (
                    <span className="jas-account-pill">Current</span>
                  ) : isSalesOnly ? (
                    <a href="/pages/get-in-touch" className="jas-account-action-link" target="_blank" rel="noreferrer">Talk to sales</a>
                  ) : (
                    <button
                      type="button"
                      className="jas-account-action-btn"
                      onClick={() => startPlanChange(key)}
                      disabled={billingActionLoading === key}
                    >
                      {billingActionLoading === key ? 'Redirecting...' : 'Select plan'}
                    </button>
                  )}
                </article>
              );
            })}
          </div>

          {billingMessage && <p className="jas-account-message">{billingMessage}</p>}

          <div className="jas-account-modal-actions">
            <button
              type="button"
              className="jas-account-portal-btn"
              onClick={openBillingPortal}
              disabled={billingActionLoading === 'portal'}
            >
              {billingActionLoading === 'portal' ? 'Opening...' : 'Open Stripe billing portal'}
            </button>
            <button
              type="button"
              className="jas-account-secondary-btn"
              onClick={() => navigate('/account')}
            >
              Full account page
            </button>
          </div>
        </div>
      </div>
    );
  };

  const openExternal = (path) => {
    window.open(path, '_blank', 'noopener,noreferrer');
  };

  const handlePMDashboardClick = (onClose) => {
    const rank = planRank[currentPlanKey] || 0;
    if (rank < 1) {
      showToast('PM Dashboard is available on Essential, Team, and Enterprise plans.', 'info');
      setBillingModalOpen(true);
      return;
    }
    onClose?.();
    navigate('/dashboard');
  };

  const renderSidebarFooter = (onClose) => (
    <div className="jas-ud-footer" ref={accountMenuRef}>
      <button
        type="button"
        className="jas-ud-footer-profile"
        onClick={() => {
          setAccountQuickMenuOpen((prev) => !prev);
          setKnowledgeMenuOpen(false);
        }}
      >
        <div className="jas-ud-footer-avatar">{userInitials}</div>
        <div className="jas-ud-footer-meta">
          <span>{userName}</span>
          <span>{currentPlanLabel}</span>
        </div>
      </button>
      <div className="jas-ud-footer-actions">
        <button
          type="button"
          className="jas-ud-footer-icon"
          title="Get apps and extensions"
          aria-label="Get apps and extensions"
          onClick={() => {
            openExternal('/pages/resources/connectors');
            setAccountQuickMenuOpen(false);
            setKnowledgeMenuOpen(false);
          }}
        >
          <FontAwesomeIcon icon={faDownload} />
        </button>
        <button
          type="button"
          className="jas-ud-footer-icon"
          title="Account menu"
          aria-label="Account menu"
          onClick={() => {
            setAccountQuickMenuOpen((prev) => !prev);
            setKnowledgeMenuOpen(false);
          }}
        >
          <FontAwesomeIcon icon={accountQuickMenuOpen ? faChevronUp : faChevronDown} />
        </button>
      </div>
      {accountQuickMenuOpen && (
        <div className="jas-ud-footer-menu">
          <div className="jas-ud-footer-email">{userEmail}</div>
          <button type="button" onClick={() => { setBillingModalOpen(true); setAccountQuickMenuOpen(false); }}>
            Upgrade plan
          </button>
          <button type="button" onClick={() => { openExternal('/login'); setAccountQuickMenuOpen(false); }}>
            Gift Jaspen
          </button>
          <div
            className="jas-ud-submenu-wrap"
            onMouseEnter={() => setKnowledgeMenuOpen(true)}
            onMouseLeave={() => setKnowledgeMenuOpen(false)}
          >
            <button type="button" className="jas-ud-submenu-trigger">
              <span>Knowledge</span>
              <span className="jas-ud-submenu-caret">›</span>
            </button>
            {knowledgeMenuOpen && (
              <div className="jas-ud-submenu">
                <button type="button" onClick={() => { openExternal('/pages/api'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>API console</button>
                <button type="button" onClick={() => { openExternal('/#about'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>About Jaspen</button>
                <button type="button" onClick={() => { openExternal('/pages/resources/tutorials'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>Tutorials</button>
                <button type="button" onClick={() => { openExternal('/pages/resources/tutorials'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>Courses</button>
                <button type="button" onClick={() => { openExternal('/pages/terms'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>Usage policy</button>
                <button type="button" onClick={() => { openExternal('/pages/privacy'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>Privacy policy</button>
                <button type="button" onClick={() => { openExternal('/pages/privacy#choices'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>Your privacy choices</button>
                <button type="button" onClick={() => { showToast('Keyboard shortcuts coming soon.', 'info'); setAccountQuickMenuOpen(false); setKnowledgeMenuOpen(false); }}>Keyboard shortcuts</button>
              </div>
            )}
          </div>
          <button type="button" onClick={() => { openExternal('/pages/support'); setAccountQuickMenuOpen(false); }}>
            Get help
          </button>
          <button type="button" onClick={() => { onClose?.(); handleLogout(); }} className="danger">
            Log out
          </button>
        </div>
      )}
    </div>
  );

  const renderUserMenuContent = (onClose) => (
    <div className="jas-ud-layout">
      <div className="jas-ud-scroll">
        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Navigate</div>
          <button className="jas-ud-item" onClick={() => handlePMDashboardClick(onClose)}>
            <FontAwesomeIcon icon={faListCheck} />
            <span className="jas-ud-item-label">PM Dashboard</span>
            {(planRank[currentPlanKey] || 0) < 1 && <span className="jas-ud-item-badge">Essential+</span>}
          </button>
          <button className="jas-ud-item" onClick={() => { onClose?.(); navigate('/sessions?view=queue'); }}>
            <FontAwesomeIcon icon={faLayerGroup} />
            <span className="jas-ud-item-label">In Queue</span>
          </button>
        </div>

        <div className="jas-ud-section">
          <div className="jas-ud-section-label">Account</div>
          <button className="jas-ud-item" onClick={() => { setBillingModalOpen(true); setAccountQuickMenuOpen(false); }}>
            <FontAwesomeIcon icon={faBolt} />
            <span className="jas-ud-item-label">Credits</span>
            <span className="jas-ud-item-badge">{billingLoading ? '...' : creditsBadge}</span>
          </button>
        </div>

        <div className="jas-ud-section">
          <button className="jas-ud-item" onClick={() => { openExternal('/pages/support'); setAccountQuickMenuOpen(false); }}>
            <FontAwesomeIcon icon={faQuestionCircle} />
            <span className="jas-ud-item-label">Get help</span>
            <span className="jas-ud-item-ext"><FontAwesomeIcon icon={faArrowUpRightFromSquare} /></span>
          </button>
        </div>
      </div>

      {renderSidebarFooter(onClose)}
    </div>
  );

  // === Speech Recognition for Voice Input ===
  useEffect(() => {
    // Check for browser support
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      console.warn('Speech recognition not supported in this browser');
      return;
    }

    if (isRecording) {
      // Start recording
      const recognition = new SpeechRecognition();
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.lang = 'en-US';

      recognition.onresult = (event) => {
        let transcript = '';
        for (let i = event.resultIndex; i < event.results.length; i++) {
          transcript += event.results[i][0].transcript;
        }
        // Append to existing input
        setInput(prev => {
          const separator = prev && !prev.endsWith(' ') ? ' ' : '';
          return prev + separator + transcript;
        });
      };

      recognition.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        setIsRecording(false);
      };

      recognition.onend = () => {
        // Only restart if still recording (user hasn't stopped)
        if (recognitionRef.current === recognition) {
          setIsRecording(false);
        }
      };

      recognitionRef.current = recognition;
      recognition.start();
    } else {
      // Stop recording
      if (recognitionRef.current) {
        recognitionRef.current.stop();
        recognitionRef.current = null;
      }
    }

    return () => {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
        recognitionRef.current = null;
      }
    };
  }, [isRecording]);

  // === Persist/Restore current session across refresh ===
  const LS_JAS_LAST_SESSION = 'jas_last_session_id';

  const setLastSessionId = (sid) => {
    try { localStorage.setItem(LS_JAS_LAST_SESSION, String(sid || '')); } catch {}
    // Optional: also store in URL so refresh/share works
    try {
      const u = new URL(window.location.href);
      u.searchParams.set('sid', String(sid || ''));
      window.history.replaceState({}, '', u.toString());
    } catch {}
  };

  const clearLastSessionId = () => {
    try { localStorage.removeItem(LS_JAS_LAST_SESSION); } catch {}
    try {
      const u = new URL(window.location.href);
      u.searchParams.delete('sid');
      window.history.replaceState({}, '', u.toString());
    } catch {}
  };

  // AI Assistant drawer state
const [aiDrawerOpen, setAiDrawerOpen] = useState(true);
const [aiInput, setAiInput] = useState('');
  // Toast notifications for chat actions
  const { toasts, showToast, dismissToast } = useToast();


  // AI drawer messages - DO NOT fabricate assistant messages
  // Assistant messages must ONLY come from backend endpoint
// Load conversation history into Assistant when scorecard is shown
// Sidebar Assistant uses the main `messages` thread as the single source of truth.
// (No separate aiMessages state.)

  // Previous session snapshot
  const [previousSessionState, setPreviousSessionState] = useState(null);

  // Fetch readiness spec on mount (ONCE) - single source, no duplicates
  useEffect(() => {
    const apiBase = API_BASE;
    let abort = false;
    (async () => {
      try {
        const res = await fetch(`${apiBase}/api/ai-agent/readiness/spec`, { credentials: 'include' });
        if (!res.ok) return;
        const json = await res.json();
        if (abort) return;

        setReadinessSpec(json || null);
        setReadinessVersion(json?.version || null);

        const map = {};
        for (const c of (json?.categories || [])) {
          map[c.key] = { label: c.label || c.key, weight: c.weight ?? null };
        }
        setSpecMap(map);
      } catch (e) {
        console.error('[fetchReadinessSpec] failed', e);
      }
    })();
    return () => { abort = true; };
  }, []);
  
  useEffect(() => {
    fetchSessions();
  }, []);

  // --- Chat helper that returns reply + readiness ---
  const chatWithReadiness = async (message, forcedSid) => {
    const sid = (() => {
      if (forcedSid && typeof forcedSid === 'string') {
        const m = document.cookie.match(/(?:^|;\s*)jaspen_sid=([^;]+)/);
        const cookieSid = m ? decodeURIComponent(m[1]) : null;
        if (cookieSid !== forcedSid) {
          document.cookie = `jaspen_sid=${encodeURIComponent(forcedSid)}; Max-Age=${30*24*3600}; Path=/; Secure; SameSite=None`;
        }
        return forcedSid;
      }
      const m = document.cookie.match(/(?:^|;\s*)jaspen_sid=([^;]+)/);
      if (m) return decodeURIComponent(m[1]);
      const v = `web_${Math.random().toString(36).slice(2)}`;
      document.cookie = `jaspen_sid=${v}; Max-Age=${30*24*3600}; Path=/; Secure; SameSite=None`;
      return v;
    })();

    const resp = await fetch(`${API_BASE}/api/ai-agent/conversation/continue`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Session-ID': sid
      },
      credentials: 'include',
      body: JSON.stringify({
        message,
        ui_mode: 'interactive',
        ui_context: {
          screen: activeTab,
          view,
          session_id: sid,
          selected_scorecard_id: selectedScorecardId || null,
          baseline_scorecard_id: baselineScorecardId || null,
        }
      })
    });

    const json = await resp.json();
return {
  text: json.reply || "",
  readiness: json.readiness || null,
  sessionId: json.session_id || sid,
  actions: json.actions || json.ui_actions || json.uiActions || []
};

  };

  // Fetch sessions (cookie OR bearer)
  const fetchSessions = async () => {
    try {
      const token = localStorage.getItem('access_token') || localStorage.getItem('token');

      const headers = { };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const response = await fetch(`${API_BASE}/api/ai-agent/threads`, {
        method: 'GET',
        headers,
        credentials: 'include'
      } );

      if (response.ok) {
        const data = await response.json();
        if (data.success && data.sessions) {
          const apiSessions = data.sessions.map((session) => {
            // Preserve any full scorecard the backend already returned
            const full = (session && typeof session.result === 'object') ? session.result : {};

            return {
              id: session.session_id,
              createdAt: new Date(session.timestamp || session.created).getTime(),
              result: {
                // prefer the persisted result blob
                ...full,
                analysis_id: full.analysis_id ?? session.session_id,
                project_name: full.project_name ?? session.name ?? 'Untitled Idea',
                market_iq_score: full.market_iq_score ?? session.score,
                status: full.status ?? session.status,
                chat_history: full.chat_history ?? session.chat_history,
                readiness: normalizeReadiness(full.readiness ?? session.readiness),
                collected_data: full.collected_data ?? session.collected_data,
              },
            };
          });
          apiSessions.sort((a, b) => b.createdAt - a.createdAt);
          setAnalysisHistory(apiSessions);
        } else {
          setAnalysisHistory([]);
        }
      } else {
        setAnalysisHistory([]);
      }
    } catch (error) {
      console.error('Error fetching sessions:', error);
      setAnalysisHistory([]);
    } finally {
      setSessionsLoading(false);
    }
  };

// Fetch a full session by id (chat_history + readiness.categories + collected_data)
async function loadSessionById(id) {
  if (!id) return null;

  const token = localStorage.getItem('access_token') || localStorage.getItem('token');
  const headers = {};
  if (token) headers['Authorization'] = `Bearer ${token}`;

  const apiBase = API_BASE;
  const url = `${apiBase}/api/ai-agent/threads/${encodeURIComponent(id )}`;

  try {
    // Attempt 1: NEW AI Agent thread fetch (JWT + cookie)
    let resp = await fetch(url, {
      method: 'GET',
      headers,
      credentials: 'include',
    });

    // If auth fails on refresh, fallback to thread bundle so we can still restore chat
    if (resp.status === 401) {
      try {
        const bundle = await MarketIQ.getThreadBundle(id, { msg_limit: 80, scn_limit: 50 });

        const bundleMsgs = Array.isArray(bundle?.messages) ? bundle.messages : [];
        const chat_history = bundleMsgs
          .map((m) => ({
            role: m.role || (m.sender === 'user' ? 'user' : 'assistant'),
            content: m.content || m.text || m.message || '',
          }))
          .filter((x) => (x.content || '').trim().length > 0);

        return {
          session_id: id,
          chat_history,
          result: bundle?.latest_analysis || bundle?.result || null,
          collected_data: bundle?.collected_data || {},
          readiness: normalizeReadiness(bundle?.readiness || null),
          status: bundle?.status || null,
        };
      } catch (e) {
        console.debug('[loadSessionById] bundle fallback failed', e);
        return null;
      }
    }

    if (!resp.ok) return null;

    const data = await resp.json();
    
    // Transform NEW API response (thread + analyses) to OLD format
    if (data.thread) {
      const thread = data.thread;
      const analyses = data.analyses || [];
      const latestAnalysis = analyses.length > 0 ? analyses[0] : null;
      
      return {
        session_id: thread.id,
        name: thread.name,
        chat_history: thread.conversation_history || [],
        readiness: normalizeReadiness(thread.readiness_snapshot || null),
        collected_data: {},
        status: latestAnalysis ? 'completed' : 'in_progress',
result: latestAnalysis ? {
  ...latestAnalysis,
  market_iq_score: latestAnalysis.overall_score,
  component_scores: latestAnalysis.scores || {}
} : null,
      };
    }
    
    // Fallback: if response doesn't have thread structure, try to use as-is
    const raw = (data && (data.session || data)) || null;
    if (!raw) return null;

    const resolvedResult =
      (raw.result && typeof raw.result === 'object' && Object.keys(raw.result).length > 0)
        ? raw.result
        : (data.result && typeof data.result === 'object' && Object.keys(data.result).length > 0)
          ? data.result
          : raw;

    return {
      ...raw,
      result: resolvedResult,
      readiness: raw.readiness ? normalizeReadiness(raw.readiness) : normalizeReadiness(null),
    };
  } catch (e) {
    console.debug('[loadSessionById] failed', e);
    return null;
  }
}

  // GOAL B: Hydrate scorecard sections if missing
  useEffect(() => {
    if (view !== 'summary') return;
    if (!sessionId) return;
    if (!analysisResult) return;
    if (hydratedScorecardRef.current.has(sessionId)) return;

    const isPartial =
      !analysisResult.decision_framework &&
      !analysisResult.investment_analysis &&
      !analysisResult.npv_irr_analysis &&
      !analysisResult.valuation &&
      !analysisResult.before_after_financials;

    if (!isPartial) {
      hydratedScorecardRef.current.add(sessionId);
      return;
    }

    hydratedScorecardRef.current.add(sessionId);

    (async () => {
      try {
        const session = await loadSessionById(sessionId);
        const full = session?.result;
        if (full && typeof full === 'object' && Object.keys(full).length > 0) {
          const normalized = normalizeAnalysis(full);
          setAnalysisResult(normalized);
          baselineRef.current = normalized;
        }
      } catch (e) {
        // no-op: hydration is best-effort
      }
    })();
  }, [view, sessionId, analysisResult]);

  // --------- Auto-open logic (unchanged) ---------
  const firstOpenedFor = useRef(null);
  const prevSessionIdRef = useRef(null);
  const lastSendAtRef = useRef(0);

  useEffect(() => {
    if (sessionId && sessionId !== prevSessionIdRef.current) {
      firstOpenedFor.current = null;
      prevSessionIdRef.current = sessionId;
      dispatchSidebar({ type: 'NEW_SESSION' });
    }
  }, [sessionId]);
// Persist last active MarketIQ session so refresh can restore it
useEffect(() => {
  if (!sessionId) return;
  setLastSessionId(sessionId);
}, [sessionId]);

// (removed duplicate /api/readiness/spec effect)

  useEffect(() => {
    const isDesktop = window.matchMedia('(min-width: 769px)').matches;
    if (
      isDesktop &&
      sessionId &&
      messages.length > 0 &&
      !sidebarState.userDismissedReadiness &&
      !sidebarState.readiness &&
      !sidebarState.history &&
      !sidebarState.settings &&
      firstOpenedFor.current !== sessionId
    ) {
      dispatchSidebar({ type: 'OPEN_READINESS' });
      firstOpenedFor.current = sessionId;
    }
  }, [
    sessionId,
    messages.length,
    sidebarState.userDismissedReadiness,
    sidebarState.readiness,
    sidebarState.history,
    sidebarState.settings
  ]);

  useEffect(() => {
    const mq = window.matchMedia('(max-width: 768px)');
    const handler = () => {};
    mq.addEventListener?.('change', handler);
    mq.addListener?.(handler);
    return () => {
      mq.removeEventListener?.('change', handler);
      mq.removeListener?.(handler);
    };
  }, []);

  useEffect(() => {
    if (!hasHistory && sidebarState.history) {
      dispatchSidebar({ type: 'CLOSE_HISTORY' });
    }
  }, [hasHistory, sidebarState.history]);

  // Autoscroll
  const endRef = useRef(null);
  // Skip exactly one server readiness ping (used right after restoring a session)
  const skipPingRef = useRef(false);
  // Auto-restore previous session on refresh (URL sid > localStorage sid)
  const didAutoRestoreRef = useRef(false);
  // (moved above to avoid TDZ / ReferenceError)

  useEffect(() => {
    if (didAutoRestoreRef.current) return;
    didAutoRestoreRef.current = true;

    (async () => {
      // Prefer URL sid, fallback to localStorage
      const urlSid = (() => {
        try { return new URLSearchParams(window.location.search).get('sid'); }
        catch { return null; }
      })();

      // GOAL A: If there is no ?sid=, do NOT restore anything.
      // Force the workspace to the default intake state.
      if (!urlSid) {
        setSessionId(null);
        setCurrentSessionId(null);
        setAnalysisResult(null);
        setMessages([]);
// (removed) sidebar uses main `messages` as the thread source of truth
        setCollectedData({});
        setReadinessAudit(null);
        setView('intake');
        setActiveTab('summary');
        dispatchSidebar({ type: 'CLOSE_ALL' });
        return;
      }
      const sid = urlSid;


      // prevent readiness “snap” edge cases during restore
      skipPingRef.current = true;

      let session = await loadSessionById(sid);

      // Fallback: if session detail is blocked by auth on refresh, restore via thread bundle
      if (!session) {
        try {
          const bundle = await MarketIQ.getThreadBundle(sid, { msg_limit: 50, scn_limit: 50 });

          // Normalize bundle messages into the same chat_history shape your UI expects
          const bundleMsgs = Array.isArray(bundle?.messages) ? bundle.messages : [];
          const chat_history = bundleMsgs.map((m) => ({
            role: m.role || (m.sender === 'user' ? 'user' : 'assistant'),
            content: m.content || m.text || m.message || '',
          })).filter(x => (x.content || '').trim().length > 0);

          session = {
            session_id: sid,
            chat_history,
            collected_data: bundle?.collected_data || {},
            status: bundle?.status || 'in_progress',
            result: bundle?.result || bundle?.analysis_result || null,
            score: bundle?.score ?? null,
          };
        } catch (e) {
          console.debug('[auto-restore] bundle fallback failed', e);
        }
      }

      if (!session) return;

      setSessionId(sid);
      setCurrentSessionId(sid);
      setLastSessionId(sid);

// Restore chat history (support both session.chat_history and session.result.chat_history)
const rawHistory =
  (Array.isArray(session?.chat_history) && session.chat_history.length > 0)
    ? session.chat_history
    : (Array.isArray(session?.result?.chat_history) && session.result.chat_history.length > 0)
      ? session.result.chat_history
      : [];

if (rawHistory.length > 0) {
  setMessages(toUiMessages(rawHistory));
}
      // Restore collected_data
      if (session.collected_data && typeof session.collected_data === 'object') {
        setCollectedData(session.collected_data);
      }

      // Restore scorecard (completed sessions)
      const fullScorecard =
        (session.result && typeof session.result === 'object' && Object.keys(session.result).length > 0)
          ? session.result
          : null;

      if ((session.status === 'completed' || session.score != null) && fullScorecard) {
        const normalized = normalizeAnalysis(fullScorecard);
        setAnalysisResult(normalized);
        baselineRef.current = normalized;

        setView('summary');
        setActiveTab('summary');
      } else {
        setView('intake');
      }

      // Always refresh readiness + scenarios from backend truth
      fetchReadinessFor(sid);
      refreshBundle(sid);
    })();

    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const scrollToEnd = () => endRef.current?.scrollIntoView({ behavior: 'smooth' });
  useEffect(scrollToEnd, [messages, busy]);

  // Hoisted function declaration to avoid TDZ issues
  function toConversationHistory(msgs) {
    return msgs.map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.text }));
  }

  // Fetch readiness snapshot (percent + categories) for a given session id
  // RETURNS the audit payload for immediate use in persistence
async function fetchReadinessFor(sid) {
  console.log('[fetchReadinessFor] ENTRY', { sid, currentSessionId, sessionId });

  if (!sid) {
    console.warn('[fetchReadinessFor] ABORT - no sid provided');
    return null;
  }

  try {
    const apiBase = API_BASE;
    const url = `${apiBase}/api/ai-agent/readiness/audit?thread_id=${encodeURIComponent(sid)}`;
    console.log('[fetchReadinessFor] fetching URL:', url);

    const res = await fetch(url, {
      method: 'GET',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        'X-Session-ID': sid,
      },
    });

    console.log('[fetchReadinessFor] response status:', res.status);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);

    const auditPayload = await res.json();
    console.log('[fetchReadinessFor] RAW auditPayload:', JSON.stringify(auditPayload, null, 2));

    const overall = {
      percent: Number(auditPayload?.overall?.percent ?? auditPayload?.percent ?? 0),
      source: auditPayload?.overall?.source ?? auditPayload?.source ?? null,
      heur_overall: Number(auditPayload?.overall?.heur_overall ?? auditPayload?.heur_overall ?? 0),
    };
    const pct = Math.max(0, Math.min(100, Math.round(overall.percent || 0)));

    console.log('[fetchReadinessFor] PARSED', {
      raw_overall_percent: auditPayload?.overall?.percent,
      raw_percent: auditPayload?.percent,
      computed_pct: pct,
      categories_count: auditPayload?.categories?.length,
    });

    const categories = Array.isArray(auditPayload?.categories) ? auditPayload.categories : [];
    const version = auditPayload?.version || null;

    const newAudit = { overall: { ...overall, percent: pct }, categories, version };
    console.log('[fetchReadinessFor] calling setReadinessAudit with:', newAudit);
    setReadinessAudit(newAudit);
    setReadinessSource(overall.source);
    setReadinessVersion(version);
    // NOTE: Do NOT map readiness categories into collectedData here. Only render from readinessAudit.categories.

    return auditPayload; // Return for immediate use in persistence
  } catch (e) {
    console.error('[fetchReadinessFor] failed', e);
    return null;
  }
}

  // =================== READINESS FETCH ===================
  // Always fetch readiness from backend when sessionId changes
  useEffect(() => {
    if (!sessionId) return;

    // Skip exactly one readiness ping (used for brand-new sessions or restores)
    if (skipPingRef.current) {
      skipPingRef.current = false;
      return;
    }

    // Always fetch from backend - no caching, no fallbacks
    fetchReadinessFor(sessionId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId]);


  // Restore original chat + show score summary when returning to Discuss (intake)
  useEffect(() => {
    if (view !== 'intake') return;
    if (!sessionId || !analysisResult) return;

    const entry =
      analysisHistory.find(s => s.id === sessionId) ||
      analysisHistory.find(s => s.result?.analysis_id === sessionId);

    const hist = entry?.result?.chat_history;
    // Restore chat history as-is - NO FABRICATED MESSAGES
    if ((messages?.length || 0) === 0 && Array.isArray(hist) && hist.length > 0) {
      setMessages(toUiMessages(hist));
    }

    // Readiness is ONLY fetched from backend via fetchReadinessFor - no sync from saved data
  }, [view, sessionId, analysisResult, analysisHistory, messages?.length]);

  // --- Upload (UI only) ---
  const fileInputRef = useRef(null);

// ======= UI Readiness - SINGLE SOURCE FROM BACKEND ====================
// ONLY source: readinessAudit.overall.percent from GET /api/readiness/audit
// NO fallbacks, NO cached values, NO guessing
const hasConversationMessages = Array.isArray(messages)
  && messages.some((m) => String(m?.text || '').trim().length > 0);
const uiReadiness = hasConversationMessages && readinessAudit?.overall?.percent != null
  ? clampPercent(readinessAudit.overall.percent)
  : 0;

// DEBUG: Track readinessAudit state changes
useEffect(() => {
  console.log('[DEBUG] readinessAudit STATE CHANGED:', {
    readinessAudit,
    uiReadiness,
    overall_percent: readinessAudit?.overall?.percent,
    categories_count: readinessAudit?.categories?.length,
  });
}, [readinessAudit, uiReadiness]);

// Readiness gate (use backend overall.percent via uiReadiness)
const canAnalyze = React.useMemo(() => {
  const hasUserTurns = messages?.some(m => m.role === 'user' && (m.text || '').trim());
return uiReadiness >= 85 && hasUserTurns;
}, [uiReadiness, messages]);

  // Utilities
  const normalize = (s) => (s || '').replace(/\s+/g, ' ').trim().toLowerCase();

  // Readiness helpers
  const clampPct = (v) => Math.max(0, Math.min(100, Math.round(Number(v) || 0)));

  const appendAssistant = (reply) => {
    const clean = (reply || '').trim();
    if (!clean) return;
    setMessages(prev => {
      const lastAi = [...prev].reverse().find(m => m.role === 'ai');
      if (lastAi && normalize(lastAi.text) === normalize(clean)) return prev;
      return [...prev, { role: 'ai', text: clean }];
    });
  };

  // === Auth ===
  const handleLogout = async (e) => {
    e?.preventDefault?.();
    try {
      const apiBase = API_BASE;
      const access  = localStorage.getItem('access_token') || localStorage.getItem('token');
      const refresh = localStorage.getItem('refresh_token');

      if (access || refresh) {
        try {
          await fetch(`${apiBase}/api/auth/logout`, {
            method: 'POST',
            headers: {
              ...(access ? { 'Authorization': `Bearer ${access}` } : {}),
              'Content-Type': 'application/json'
            },
            credentials: 'include',
            body: JSON.stringify({ refresh_token: refresh })
          });
        } catch {}
      }

      ['access_token','token','refresh_token'].forEach(k => localStorage.removeItem(k));
      document.cookie = 'jaspen_sid=; Max-Age=0; Path=/; Secure; SameSite=None';
    } finally {
      window.location.replace('/logout');
    }
  };

  // === Conversation Start ===
  // Flow: Call MarketIQ.convoStart → set session → await audit → append message → save
  async function startConversation(description) {
    console.log('[startConversation] ENTRY', { description: description?.substring(0, 50) });
    setBusy(true); setError(null);

    // Clear old readiness immediately to show 0% for new conversation
    setReadinessAudit(null);

    try {
      // Step 1: Call MarketIQ.convoStart (client wrapper)
      const data = await MarketIQ.convoStart({ description, system_prompt: null });

      console.log('[startConversation] convoStart returned:', {
        thread_id: data.thread_id,
        session_id: data.session_id,
        readiness: data.readiness,
      });

      // Step 2: Set sessionId (must use real thread_id/session_id from backend)
      const sid = data.thread_id || data.session_id;
      if (!sid) {
        throw new Error('Missing thread_id from convoStart response');
      }
      console.log('[startConversation] setting sessionId to:', sid);
      setSessionId(sid);
      setCurrentSessionId(sid);
      dispatchSidebar({ type: "OPEN_READINESS" });

      // Step 3: await GET /api/readiness/audit (authoritative)
      console.log('[startConversation] calling fetchReadinessFor with sid:', sid);
      await fetchReadinessFor(sid);
      
      const reply = (typeof data?.message === 'string' && data.message.trim()) ||
                    (typeof data?.reply === 'string' && data.reply.trim());

      // Step 4: Append assistant message ONLY if backend returned one
      if (reply) {
        appendAssistant(reply);
      }


      // REMOVED - AI Agent backend handles persistence automatically
      // await saveSessionToBackend({...});

      setPreviousSessionState({
        sessionId: sid,
        messages: [{ role: "user", text: description }, { role: "ai", text: reply }],
        readiness: data.readiness || 0,
        collectedData: data.collected_data || {},
      });

      await fetchSessions();
    } catch (e) {
      setError("Could not start the conversation. Please try again.");
      console.error(e);
    } finally {
      setBusy(false);
    }
  }

  // === Conversation Continue ===
  // Flow: Call MarketIQ.convoContinue → append message → await audit → persist using returned payload
async function continueConversation(userText) {
  console.log('[continueConversation] ENTRY', {
    sessionId,
    currentSessionId,
    userText: userText?.substring(0, 50),
    messagesCount: messages?.length,
  });

  if (!sessionId) {
    console.warn('[continueConversation] ABORT - no sessionId');
    return;
  }
  setBusy(true);
  setError(null);

  try {
    const conversation_history = [
      ...toConversationHistory(messages),
      { role: "user", content: userText },
    ];

    console.log('[continueConversation] calling MarketIQ.convoContinue with session_id:', sessionId);

    // Step 1: Call MarketIQ.convoContinue (client wrapper)
    const data = await MarketIQ.convoContinue({
      session_id: sessionId,
      user_message: userText,
      conversation_history,
    });

    console.log('[continueConversation] convoContinue returned:', {
      hasReply: Boolean(data?.reply || data?.message),
      readinessFromConvo: data?.readiness,
      thread_id_in_response: data?.thread_id,
    });

    const serverReply = (typeof data?.reply === 'string' && data.reply.trim()) ||
                        (typeof data?.message === 'string' && data.message.trim());

    // Step 2: Append assistant message ONLY if backend returned one
    if (serverReply) {
      appendAssistant(serverReply);
    }

    console.log('[continueConversation] about to call fetchReadinessFor with sessionId:', sessionId);

    // Step 3: await GET /api/readiness/audit
    const auditPayload = await fetchReadinessFor(sessionId);

    console.log('[continueConversation] fetchReadinessFor returned auditPayload:', {
      hasAudit: Boolean(auditPayload),
      overall_percent: auditPayload?.overall?.percent,
      categories_count: auditPayload?.categories?.length,
    });

    const updatedCollected = data?.collected_data || collectedData;
    setCollectedData(updatedCollected);

    // Step 4: Update UI state with new readiness
    if (auditPayload) {
      const pct = clampPercent(auditPayload.overall?.percent ?? 0);
      const categories = Array.isArray(auditPayload?.categories) ? auditPayload.categories : [];
      const version = auditPayload?.version || null;

      console.log('[continueConversation] setting readinessAudit with pct:', pct);

      setReadinessAudit({
        overall: { ...auditPayload.overall, percent: pct },
        categories,
        version
      });
    } else {
      console.warn('[continueConversation] auditPayload is null/undefined - readiness NOT updated');
    }

    // Note: AI Agent backend handles persistence automatically
    // No need to call saveSessionToBackend - readiness is already saved by backend

    setPreviousSessionState({
      sessionId,
      messages: [
        ...messages,
        { role: "user", text: userText },
        { role: "ai", text: serverReply },
      ],
      readiness: auditPayload ? {
        percent: clampPercent(auditPayload.overall?.percent ?? 0),
        categories: auditPayload.categories || [],
        updated_at: new Date().toISOString()
      } : {
        percent: 0,
        categories: [],
        updated_at: new Date().toISOString()
      },
      collectedData: updatedCollected,
    });
  } catch (e) {
    setError("Having trouble continuing the conversation. Please resend.");
    console.error(e);
  } finally {
    setBusy(false);
  }
}
// === Begin Project (confirm + backend create + spinner + navigate) ===
const [beginBusy, setBeginBusy] = useState(false);
const [beginMsg, setBeginMsg] = useState("Generating your project plan…");

async function onBeginProject() {
    const suggestedName = deriveIdeaTitle({
      result: activeScorecard || analysisResult,
      messages,
      fallback: 'Untitled Idea',
    });

    const ok = window.confirm(
        `Begin a project from your Jaspen context?\n\n` +
        `Project name: "${suggestedName}"\n\n` +
        `This will create/update a project and plan in your Sekki workspace.`
    );
    if (!ok) return;

    setBeginBusy(true);
    setBeginMsg("Building your project plan…");

    try {
        // Use your session id when available so future runs "replace" the same project
        const sid = (currentSessionId || sessionId || `web_${Date.now()}`);

        // IMPORTANT: send the actual scorecard context already rendered in the UI
        const scorecard = activeScorecard || analysisResult || null;

        const body = {
            sid,
            project_name: suggestedName,
            scorecard_id: selectedScorecardId || null,
            scorecard,                       // <--- this is the key fix
            dry_run: false,
            persist: true,
            mode: 'replace',
            commit_message: 'begin-project from Jaspen'
        };

        const resp = await fetch(`${API_BASE}/api/projects/generate/ai`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body)
        });

        const json = await resp.json().catch(() => ({}));

        if (!resp.ok) {
            const detail = json?.detail || json?.error || `HTTP ${resp.status}`;
            setBeginMsg(`Could not create the plan: ${detail}`);
            setTimeout(() => setBeginBusy(false), 1200);
            return;
        }

        const projectId = json?.project_id;
        const redirect = json?.redirect || (projectId
            ? `/ops/project-planning?projectId=${encodeURIComponent(projectId)}`
            : null
        );

        setBeginMsg("Plan ready — opening Project Planning…");
        setTimeout(() => {
            if (redirect) {
                window.location.href = redirect;
            } else {
                setBeginBusy(false);
                alert('Plan created, but no redirect was provided.');
            }
        }, 600);
    } catch (e) {
        console.error('[Begin Project] failed', e);
        setBeginMsg('Something went wrong. Please try again.');
        setTimeout(() => setBeginBusy(false), 1200);
    }
}



  // PROMPT ALIGNMENT: Handle adopted scenario scorecard snapshots
  const handleAdoptScorecard = (adoptedSnapshot) => {
    if (!adoptedSnapshot || !adoptedSnapshot.id) {
      console.warn('[handleAdoptScorecard] Invalid snapshot:', adoptedSnapshot);
      return;
    }
    
    setScorecardSnapshots(prev => {
      // Dedupe by id
      const existing = prev.find(s => s.id === adoptedSnapshot.id);
      if (existing) return prev;
      
      return [...prev, {
        ...adoptedSnapshot,
        isBaseline: false,
        createdAt: Date.now()
      }];
    });
    
    // Optionally auto-select the adopted scorecard
    setSelectedScorecardId(adoptedSnapshot.id);
  };

  const handleScenarioAdopt = async (adoptedScenario, label) => {
    if (!adoptedScenario || (!adoptedScenario.id && !adoptedScenario.analysis_id)) {
      console.warn('[handleScenarioAdopt] Invalid scenario:', adoptedScenario);
      showToast('Invalid scenario - cannot adopt', 'error');
      return;
    }

    const tid = currentSessionId || sessionId;
    if (!tid) {
      showToast('No active session', 'error');
      return;
    }

    try {
      const scenarioId = adoptedScenario.id || adoptedScenario.analysis_id;
      
      // 1) Persist adoption to backend
      await MarketIQ.adoptScenario(scenarioId);

      // 2) Create snapshot for adopted scenario
      const adoptedSnapshot = {
        ...adoptedScenario,
        id: scenarioId,
        label: label || adoptedScenario.label || 'Adopted Scenario',
        isBaseline: false,
        adoptedAt: Date.now(),
        market_iq_score: adoptedScenario.overall_score || adoptedScenario.market_iq_score || 0,
      };

      // 3) Update snapshots - PRESERVE BASELINE
      setScorecardSnapshots(prev => {
        // Keep baseline (isBaseline: true)
        const baseline = prev.find(s => s.isBaseline === true);
        
        // Remove old version of this scenario if exists
        const others = prev.filter(s => s.id !== scenarioId && !s.isBaseline);
        
        // Build new array: baseline first, then others, then adopted
        const newSnapshots = [];
        if (baseline) newSnapshots.push(baseline);
        newSnapshots.push(...others, adoptedSnapshot);
        
        return newSnapshots;
      });

      // 4) Select the adopted scorecard
      setSelectedScorecardId(scenarioId);

      // 5) Update current analysis result
      setAnalysisResult(adoptedScenario);

      // 6) Refresh bundle to sync
      await refreshBundle(tid);

      showToast(`${label || 'Scenario'} adopted successfully`, 'success');
    } catch (err) {
      console.error('[handleScenarioAdopt] failed:', err);
      showToast('Failed to adopt scenario', 'error');
    }
  };

  // === Finish & Analyze ===
  async function onFinishAnalyze() {
    if (!sessionId || busy) {
      console.warn('[Finish&Analyze] blocked', { sessionId, currentSessionId, busy, uiReadiness, canAnalyze, msgCount: messages?.length });
      return;
    }
    console.log('[Finish&Analyze] starting', { sessionId, currentSessionId, uiReadiness, canAnalyze, msgCount: messages?.length });
    setBusy(true);
    setError(null);

    const normalize = (r = {}) => {
      const compat = r.compat || {};
      const comps  = r.component_scores || compat.components || {};
      const fin    = r.financial_impact || compat.financials || {};

      let score = Number.parseInt(Number(r.market_iq_score ?? compat.score ?? 0), 10);
      if (!Number.isFinite(score)) score = 0;
      const score_category =
        r.score_category ||
        (score >= 80 ? 'Excellent' : score >= 60 ? 'Good' : score >= 40 ? 'Fair' : 'At Risk');

      const toInt = (v) => {
        const n = Number.parseInt(Number(v), 10);
        return Number.isFinite(n) ? n : 0;
      };
      const component_scores = {
        financial_health:       toInt(comps.financial_health ?? comps.financialHealth ?? comps.financial ?? comps.economics),
        operational_efficiency: toInt(comps.operational_efficiency ?? comps.operationalEfficiency ?? comps.execution ?? comps.operations),
        market_position:        toInt(comps.market_position ?? comps.marketPosition ?? comps.market ?? comps.strategy),
        execution_readiness:    toInt(comps.execution_readiness ?? comps.executionReadiness ?? comps.team ?? comps.readiness),
      };

      const project_name =
        r.project_name || compat.title || r.title || 'Untitled Idea';

      const risks = r.risks || r.top_risks || [];

      return {
        ...r,
        market_iq_score: score,
        score_category,
        component_scores,
        financial_impact: {
          ebitda_at_risk:   fin.ebitda_at_risk   ?? fin.ebitdaAtRisk   ?? fin.ebitda ?? fin.risk,
          potential_loss:   fin.potential_loss   ?? fin.potentialLoss,
          roi_opportunity:  fin.roi_opportunity  ?? fin.roiOpportunity,
          projected_ebitda: fin.projected_ebitda ?? fin.projectedEbitda,
        },
        project_name,
        risks,
      };
    };

    try {
      const transcript = messages
        .map(m => `${m.role === 'user' ? 'User' : 'AI'}: ${m.text}`)
        .join('\n');

      // derive a stable numeric seed from the session id (same inputs => same score)
      const sid  = currentSessionId || sessionId;
      const seed = Number(String(sid).replace(/\D/g, '')) % 2147483647 || 123456;

const data = await MarketIQ.analyzeFromConversation({
  session_id: sid, transcript, deterministic: true, seed
});
console.log('[Finish&Analyze] analyze response', { keys: data ? Object.keys(data) : null, has_analysis_result: Boolean(data?.analysis_result) });
// DEBUG: Check if meta.extracted_levers survived
console.log('[Finish&Analyze] data.analysis_result.meta?', data?.analysis_result?.meta);
console.log('[Finish&Analyze] data.analysis_result.meta.extracted_levers?', data?.analysis_result?.meta?.extracted_levers);

      const raw = (data && data.analysis) ? data.analysis : (data && data.analysis_result) ? data.analysis_result : (data || {});
      console.log('[Finish&Analyze] raw object keys:', Object.keys(raw));
      console.log('[Finish&Analyze] raw.meta?', raw?.meta);

      // Map backend fields to frontend expectations
      const mapped = {
        ...raw,
        market_iq_score: raw.overall_score || raw.market_iq_score || 0,
        component_scores: raw.scores || raw.component_scores || {},
        project_name: raw.name || raw.project_name || deriveIdeaTitle({ messages, fallback: 'Untitled Idea' }),
        inputs: raw.inputs || raw.analysis_result?.inputs || null,
        compat: raw.compat || raw.analysis_result?.compat || null,
      };

      const result = { ...normalize(mapped), analysis_id: sid };

      if (!result || Object.keys(result).length === 0) {
        throw new Error("No analysis_result returned");
      }

      // DEBUG: Log what setAnalysisResult receives
      console.log('[Finish&Analyze] result passed to setAnalysisResult:', JSON.stringify(result, null, 2));
      console.log('[Finish&Analyze] result.meta?', result?.meta);
      console.log('[Finish&Analyze] result.inputs?', result?.inputs);
      console.log('[Finish&Analyze] result.compat?', result?.compat);
      setAnalysisResult(result);

      // Mark baseline scorecard
      const baselineSnapshot = {
        ...result,
        id: result.analysis_id || result.id || sessionId,
        label: 'Baseline',
        isBaseline: true,
        createdAt: Date.now(),
      };

      // Initialize scorecardSnapshots with baseline
      setScorecardSnapshots([baselineSnapshot]);
      setSelectedScorecardId(baselineSnapshot.id);
      setBaselineScorecardId(baselineSnapshot.id);
      baselineRef.current = result; // Store baseline reference

      await refreshBundle(currentSessionId || sessionId);

// REMOVED - AI Agent backend handles persistence automatically
// await saveSessionToBackend({...});


      await fetchSessions();
      setView('summary');
      setActiveTab('summary');
      setTimeout(() => {
        setView('summary');
        setActiveTab('summary');
      }, 0);
    } catch (e) {
      setError("Could not build the scorecard yet. Try adding one more detail, then Finish again.");
      console.error(e);
    } finally {
      setBusy(false);
    }
  }

  // === Input handling ===
  function onSubmit() {
    const now = Date.now();
    if (now - (lastSendAtRef.current || 0) < 500) return;
    lastSendAtRef.current = now;

    const text = (input || '').trim();
    if (busy) return;
    if (!text && (!pendingFiles || pendingFiles.length === 0)) return;

    const attachments = (pendingFiles || []).map(f => ({
      name: f.name,
      size: f.size,
      type: f.type,
      preview: f.preview || null,
      uploading: true,
    }));

    setMessages(prev => [
      ...prev,
      {
        role: 'user',
        text: text || '(attachments)',
        attachments,
      },
    ]);

    setInput('');
    setPendingFiles([]);

    const placeholder = text || `Uploaded ${attachments.length} file(s)`;
    if (!sessionId) startConversation(placeholder);
    else continueConversation(placeholder);
  }

  function onKey(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      onSubmit();
    }
  }

  function onFilesSelected(e) {
    const picked = Array.from(e.target.files || []);
    if (!picked.length) return;
    const MAX_FILES_AT_ONCE = 10;
    const toAdd = picked.slice(0, MAX_FILES_AT_ONCE).map((f) => ({
      name: f.name,
      size: f.size,
      type: f.type || 'application/octet-stream',
      file: f,
      preview: f.type?.startsWith('image/') ? URL.createObjectURL(f) : null,
    }));
    setPendingFiles((prev) => [...prev, ...toAdd]);
    e.target.value = '';
  }

  // === AI Assistant Handlers ===
  const toggleAIDrawer = () => setAiDrawerOpen(!aiDrawerOpen);

  // === Sidebar content for Refine & Rescore (mini scorecard, no duplicate buttons) ===
  const renderMiniScorecard = (result) => {
    if (!result) return null;
    const comps = result.component_scores || result.scores || result.compat?.components || {};
    const score = result.market_iq_score ?? result.overall_score ?? result.score ?? result.compat?.score ?? 0;
    const category = result.score_category ||
      (Number(score) >= 80 ? 'Excellent' : Number(score) >= 60 ? 'Good' : Number(score) >= 40 ? 'Fair' : 'At Risk');
    const items = [
      { key: 'financial_health',       label: 'Financial Health',       val: comps.financial_health ?? comps.financialHealth ?? comps.financial ?? comps.economics ?? 0 },
      { key: 'operational_efficiency', label: 'Operational Efficiency', val: comps.operational_efficiency ?? comps.operationalEfficiency ?? comps.operations ?? comps.execution ?? 0 },
      { key: 'market_position',        label: 'Market Position',        val: comps.market_position ?? comps.marketPosition ?? comps.market ?? comps.strategy ?? 0 },
      { key: 'execution_readiness',    label: 'Execution Readiness',    val: comps.execution_readiness ?? comps.executionReadiness ?? comps.readiness ?? comps.team ?? 0 },
    ];
    const clamp = (n) => Math.max(0, Math.min(100, Math.round(Number(n) || 0)));
    const risks = Array.isArray(result.risks) ? result.risks : [];

    return (
      <div className="jas-mini-scorecard">
        <div className="jas-mini-scorecard-head">
          <div className="jas-mini-project">{deriveIdeaTitle({ result, messages, fallback: 'Untitled Idea' })}</div>
          <div className="jas-mini-scoreline">
            <span className="jas-mini-score">{clamp(score)}</span>
            <span className="jas-mini-outof">/100</span>
            <span className="jas-mini-cat">{category ? `• ${category}` : ''}</span>
          </div>
        </div>

        <div className="jas-mini-components">
          {items.map((it) => (
            <div key={it.key} className="jas-mini-row">
              <div className="jas-mini-row-top">
                <span className="jas-mini-label">{it.label}</span>
                <span className="jas-mini-val">{clamp(it.val)}</span>
              </div>
              <div className="jas-mini-bar">
                <div className="jas-mini-bar-fill" style={{ width: `${clamp(it.val)}%` }} />
              </div>
            </div>
          ))}
        </div>

        {risks.length > 0 && (
          <div className="jas-mini-risks">
            <div className="jas-mini-section-title">Top Risks</div>
            <ul className="jas-mini-risklist">
              {risks.slice(0, 3).map((r, i) => (
                <li key={i}>{String(r)}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    );
  };

  // === Chat Command Handlers ===
  const chatCommandHandlers = {
    [ChatActionTypes.SCORECARD_SELECT]: (payload) => {
      const { scorecardId } = payload;
      if (scorecardId && scorecardSnapshots.find(s => s.id === scorecardId)) {
        setSelectedScorecardId(scorecardId);
        showToast(`Switched to ${scorecardSnapshots.find(s => s.id === scorecardId)?.label || 'scorecard'}`, 'success');
      } else {
        showToast('Scorecard not found', 'error');
      }
    },
    
[ChatActionTypes.SCORECARD_UPDATE_FIELD]: async (payload) => {
  const {
    scorecardId,
    section,          // e.g. "decision_framework"
    rowLabel,         // e.g. "Overall Recommendation"
    updates           // e.g. { decision: "Maybe", notes: "Funding Needed" }
  } = payload || {};

  const baseId = scorecardId || selectedScorecardId || baselineScorecardId;
  if (!baseId) {
    showToast('No scorecard available to update', 'error');
    return;
  }

  // Source scorecard = snapshot if available, else fall back to current analysisResult
  const source =
    (Array.isArray(scorecardSnapshots) ? scorecardSnapshots.find(s => s.id === baseId) : null) ||
    (analysisResult ? { ...analysisResult, id: baseId } : null);

  if (!source) {
    showToast('Scorecard not found', 'error');
    return;
  }

  // Create an edited copy id (baseline stays immutable)
  const editedId = `${baseId}__edited`;

  const applyDecisionFrameworkUpdate = (scorecard) => {
    const df = scorecard?.decision_framework;

    // If decision_framework is not an array, nothing to edit
    if (!Array.isArray(df)) return scorecard;

    const target = String(rowLabel || '').trim();
    const nextDf = df.map((row) => {
      const label = String(row?.label || row?.name || '').trim();
      if (label !== target) return row;

      return {
        ...row,
        ...(updates && typeof updates === 'object' ? updates : {}),
      };
    });

    return { ...scorecard, decision_framework: nextDf };
  };

  let next = { ...source };

  if ((section || '') === 'decision_framework') {
    next = applyDecisionFrameworkUpdate(next);
  } else {
    // Generic fallback: shallow merge
    if (updates && typeof updates === 'object') next = { ...next, ...updates };
  }

  // Mark as edited snapshot
  next = {
    ...next,
    id: editedId,
    label: (source.label ? `${source.label} (Edited)` : 'Edited Scorecard'),
    isBaseline: false,
    createdAt: Date.now(),
  };

  // 1) Upsert edited snapshot + select it
  setScorecardSnapshots((prev) => {
    const arr = Array.isArray(prev) ? prev : [];
    const exists = arr.some(s => s.id === editedId);
    return exists ? arr.map(s => (s.id === editedId ? next : s)) : [...arr, next];
  });

  setSelectedScorecardId(editedId);

  // 2) Tell the AI it happened (this becomes part of the thread context)
  try {
    const changedKeys =
      updates && typeof updates === 'object'
        ? Object.entries(updates).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(', ')
        : '';
    appendAssistant(
      `✅ Updated ${section || 'scorecard'} → "${rowLabel || ''}"${changedKeys ? ` (${changedKeys})` : ''}.`
    );
  } catch {}

  showToast('Updated scorecard table', 'success');

  // 3) Persist so refresh restores:
  // - Keep original baseline in result._baseline_scorecard (first time only)
  // - Persist snapshots + selected scorecard id inside the result blob
  try {
    const sid = currentSessionId || sessionId;
    const baselineId = baselineScorecardId || (analysisResult?.analysis_id ?? sid);

    // Determine baseline snapshot to preserve (if not already preserved)
    const baselineSnap =
      (Array.isArray(scorecardSnapshots) ? scorecardSnapshots.find(s => s.id === baselineId) : null) ||
      (analysisResult ? { ...analysisResult, id: baselineId, label: 'Baseline', isBaseline: true } : null);

    const safeBaseline = baselineSnap ? { ...baselineSnap } : null;
    if (safeBaseline) {
      delete safeBaseline.scorecard_snapshots;
      delete safeBaseline._baseline_scorecard;
      delete safeBaseline.selected_scorecard_id;
    }

    // Build snapshots we want persisted (baseline + edited + others)
    const currentSnaps = Array.isArray(scorecardSnapshots) && scorecardSnapshots.length > 0
      ? scorecardSnapshots
      : (baselineSnap ? [baselineSnap] : []);

    const withEdited = (() => {
      const exists = currentSnaps.some(s => s.id === editedId);
      return exists ? currentSnaps.map(s => (s.id === editedId ? next : s)) : [...currentSnaps, next];
    })();

    // Also ensure baseline has isBaseline true
    const persistedSnaps = withEdited.map(s => {
      if (!s) return s;
      if (s.id === baselineId) return { ...s, isBaseline: true, label: s.label || 'Baseline' };
      return s;
    });

    // Persist: store snapshots + selection inside the result blob
    // IMPORTANT: We do NOT set analysisResult = next (baseline stays baseline in state)
    const resultToPersist = {
      ...(analysisResult || {}),
      _baseline_scorecard: (analysisResult?._baseline_scorecard || safeBaseline || null),
      scorecard_snapshots: persistedSnaps,
      selected_scorecard_id: editedId,
    };

    // REMOVED - AI Agent backend handles persistence automatically
    // await saveSessionToBackend({...});
  } catch (e) {
    console.error('[SCORECARD_UPDATE_FIELD] persist failed', e);
    showToast('Updated UI, but failed to persist changes', 'error');
  }
},
    
        [ChatActionTypes.SCENARIO_SET_INPUT]: (payload) => {
      // payload examples:
      // { scenario: 'A', key: 'budget', value: 250000 }
      // { scenarioId: 'scenarioA', lever: 'budget', value: 250000 }
      setActiveTab('scenario');
      setView('scenario');

      const api = scenarioModelerRef.current;
      if (!api || typeof api.setScenarioInput !== 'function') {
        showToast('Scenario inputs are not ready yet', 'error');
        return;
      }

      const ok = api.setScenarioInput(payload);
      if (ok) showToast('Scenario input updated', 'success');
      else showToast('Could not apply scenario input', 'error');
    },

    
        [ChatActionTypes.SCENARIO_RUN]: async (payload) => {
      setActiveTab('scenario');
      setView('scenario');

      const api = scenarioModelerRef.current;
      if (!api || typeof api.runScenario !== 'function') {
        showToast('Scenario runner is not ready yet', 'error');
        return;
      }

      showToast('Running scenario…', 'info');
      try {
        await api.runScenario(payload);
        showToast('Scenario complete', 'success');
      } catch (e) {
        console.error('[SCENARIO_RUN] failed', e);
        showToast('Scenario run failed', 'error');
      }
    },

    
        [ChatActionTypes.SCENARIO_ADOPT]: async (payload) => {
      setActiveTab('scenario');
      setView('scenario');

      const api = scenarioModelerRef.current;
      if (!api || typeof api.adoptScenario !== 'function') {
        showToast('Scenario adoption is not ready yet', 'error');
        return;
      }

      try {
        const adopted = await api.adoptScenario(payload);
        if (adopted) showToast('Scenario adopted', 'success');
        else showToast('Nothing to adopt yet', 'info');
      } catch (e) {
        console.error('[SCENARIO_ADOPT] failed', e);
        showToast('Scenario adoption failed', 'error');
      }
    },

    
    [ChatActionTypes.PROJECT_BEGIN]: async (payload) => {
      const scorecardId = payload.scorecardId || selectedScorecardId;
      if (!scorecardId) {
        showToast('No scorecard selected', 'error');
        return;
      }
      
      try {
        // Call the beginProject flow
        const projectData = await MarketIQ.beginProject({
          threadBundleId: sessionId,
          scorecardId: scorecardId,
          projectName: deriveIdeaTitle({ result: activeScorecard || analysisResult, messages, fallback: 'Untitled Idea' })
        });
        
        showToast('Project created successfully!', 'success');
        
        // Navigate to project planning
        navigate(`/workspace/${sessionId}/project/${projectData.projectId}`, {
          state: { scorecardId, ...projectData }
        });
      } catch (error) {
        console.error('Begin project failed:', error);
        showToast('Failed to create project', 'error');
      }
    },
  };
  
  const { dispatchChatActions } = useChatCommands(chatCommandHandlers);

const sendAIMessage = async () => {
  const text = (aiInput || '').trim();
  if (!text || !sessionId || busy) return;

  setAiInput('');
  setBusy(true);
  setError(null);

  try {
    // 1) Add the user's message into the ONE shared thread UI
    setMessages(prev => [...prev, { role: 'user', text }]);

    // 2) Call the endpoint that can return Interactive actions
    const resp = await chatWithReadiness(text, currentSessionId || sessionId);

    // 3) Add assistant reply into the shared thread UI
    if (resp?.text) {
      setMessages(prev => [...prev, { role: 'ai', text: resp.text }]);
    }

    // 4) Refresh readiness (authoritative) and persist the full updated thread
    const sid = resp?.sessionId || currentSessionId || sessionId;
    const auditPayload = await fetchReadinessFor(sid);

    const readinessObj = auditPayload ? {
      percent: clampPercent(auditPayload.overall?.percent ?? 0),
      categories: auditPayload.categories || [],
      updated_at: new Date().toISOString()
    } : {
      percent: 0,
      categories: [],
      updated_at: new Date().toISOString()
    };

    // Build the chat_history from the latest visible thread
    const nextChatHistory = [
      ...toConversationHistory(messages),
      { role: 'user', content: text },
      ...(resp?.text ? [{ role: 'assistant', content: resp.text }] : []),
    ];

    // REMOVED - AI Agent backend handles persistence automatically
    // await saveSessionToBackend({...});

    // 5) Interactive actions
    // parseUIActions expects "response-ish" data; provide the fields it might look for.
const actionEnvelope = {
  ...resp,
  reply: resp?.text,
  text: resp?.text,
  actions: resp?.actions || []
};

const uiActions = parseUIActions(actionEnvelope);
    if (uiActions?.length) {
      const results = dispatchChatActions(uiActions);
      results.forEach(({ success, error }) => {
        if (!success) showToast(`Action failed: ${error}`, 'error');
      });
    }
  } catch (err) {
    console.error('[sendAIMessage] failed', err);
    setMessages(prev => [...prev, { role: 'ai', text: 'Sorry — I hit an error. Please try again.' }]);
  } finally {
    setBusy(false);
  }
};

  // === Helpers ===
  const handleNewAnalysis = (forceNew = false) => {
    if (!forceNew && previousSessionState && previousSessionState.sessionId === sessionId) {
      setView('intake');
      setMessages(previousSessionState.messages);
      setCollectedData(previousSessionState.collectedData);
      setAnalysisResult(null);
      setError(null);
      dispatchSidebar({ type: 'OPEN_READINESS' });
      return;
    }

    clearLastSessionId();
    setView('intake');
    setSessionId(null);
    setCurrentSessionId(null);
    setMessages([]);
    setInput('');
    setBusy(false);
    setReadinessAudit(null);
    setAnalysisResult(null);
    setError(null);
    setSavedScenarios([]);
    setCollectedData({});
    dispatchSidebar({ type: 'CLOSE_READINESS' });
    setPreviousSessionState(null);
  };

  // ======== FIXED: Select analysis (history restore) ========================
  const handleSelectAnalysis = async (result) => {
  // Block the very first readiness ping after selecting history
  skipPingRef.current = true;

  // Prefer a full record from the backend if the list item looks incomplete
  const baseId =
    result?.analysis_id ||
    result?.session_id ||
    result?.id;

  const looksIncomplete =
    !Array.isArray(result?.chat_history) ||
    (result?.chat_history?.length ?? 0) < 1 ||
    !result?.readiness ||
    !Array.isArray(result?.readiness?.categories) ||
    (result?.readiness?.percent == null &&
     result?.readiness?.readiness_percent == null &&
     result?.readiness?.value == null);

  const full = looksIncomplete && baseId ? await loadSessionById(baseId) : null;

  // Merge shallowly: prefer fields from the full fetch when present
  const merged = full
    ? {
        ...result,
        ...full,
        readiness: full.readiness ?? result.readiness,
        chat_history: Array.isArray(full.chat_history) ? full.chat_history : result.chat_history,
        collected_data: full.collected_data ?? result.collected_data,
        status: full.status ?? result.status,
        analysis_id: full.session_id ?? result.analysis_id,
        project_name: full.name ?? result.project_name,
        market_iq_score: (full.score ?? result.market_iq_score),
      }
    : result;

  // Readiness normalization handled by normalizeReadiness() helper
  // Readiness is ONLY fetched from backend via fetchReadinessFor - no session cache

  // Branch: in-progress sessions return to intake with chat restored
  if (merged?.status === 'in_progress' && Array.isArray(merged.chat_history)) {
    const sid = merged.analysis_id || merged.session_id || baseId || `restored_${Date.now()}`;
    setSessionId(sid);
    setCurrentSessionId(sid);

    const restoredMessages = toUiMessages(merged.chat_history);
    setMessages(restoredMessages);

    setCollectedData(merged.collected_data || {});
    setView('intake');
    dispatchSidebar({ type: 'CLOSE_HISTORY' });
    dispatchSidebar({ type: 'OPEN_READINESS' });
    fetchReadinessFor(sid);


    setPreviousSessionState({
      sessionId: sid,
      messages: restoredMessages,
      collectedData: merged.collected_data || {},
    });
    return;
  }

// Completed session -> workspace summary (prefer the persisted result blob)
try {
  const id =
    merged?.analysis_id ??
    merged?.session_id ??
    baseId ??
    `restored_${Date.now()}`;

  setSessionId(id);
  const restoredMessages = toUiMessages(merged?.chat_history || merged?.result?.chat_history || []);
  if (restoredMessages.length > 0) {
    setMessages(restoredMessages);
  }

  setCurrentSessionId(id); // ADD THIS LINE - was missing!
  
// Try multiple paths to find the full scorecard
// Backend stores complete scorecard in session.result field
const full =
  (merged?.result && typeof merged.result === 'object' && Object.keys(merged.result).length > 0)
    ? merged.result
    : (merged && typeof merged === 'object' && merged.market_iq_score)
      ? merged
      : null;

// GOAL B part 2: Check for missing detailed sections and hydrate if needed
const missingSections =
  !full?.decision_framework &&
  !full?.investment_analysis &&
  !full?.npv_irr_analysis &&
  !full?.valuation &&
  !full?.before_after_financials;

if (missingSections) {
  const fresh = await loadSessionById(id);
  const freshScorecard = fresh?.result || fresh;
  if (freshScorecard) {
    const normalized = normalizeAnalysis(freshScorecard);
    setAnalysisResult(normalized);
    baselineRef.current = normalized;
  } else {
    const normalized = normalizeAnalysis(full || merged || {});
    setAnalysisResult(normalized);
    baselineRef.current = normalized;
  }
} else {
  const normalized = normalizeAnalysis(full);
  setAnalysisResult(normalized);
  baselineRef.current = normalized;
}

  dispatchSidebar({ type: 'CLOSE_HISTORY' });
  // Readiness sidebar only applies to in-progress (incomplete) sessions
  // Completed sessions go directly to summary view
  setView('summary');
  setActiveTab('summary');

} catch (e) {
  console.error('[handleSelectAnalysis] hydrate failed', e, { merged });
  // Safe fallback so the UI still renders something
const normalizedFallback = normalizeAnalysis(merged || {});
setAnalysisResult(normalizedFallback);
if (!baselineRef.current) baselineRef.current = normalizedFallback; // only set if not set yet
}
  }

  // Delete a session
  const deleteAnalysisById = async (itemId) => {
    try {
      const token = localStorage.getItem('access_token') || localStorage.getItem('token');

      const headers = { };
      if (token) headers['Authorization'] = `Bearer ${token}`;

await fetch(`${API_BASE}/api/ai-agent/threads/${itemId}`, {
  method: 'DELETE',
  headers,
  credentials: 'include'
} );
    } catch (error) {
      console.error('Error deleting session from backend:', error);
    }
  };

  const handleDeleteAnalysis = async (itemId) => {
    await deleteAnalysisById(itemId);
    await fetchSessions();
  };

  const handleClearHistory = async () => {
    if (!analysisHistory.length || clearingHistory) return;
    const ok = window.confirm(`Delete all ${analysisHistory.length} history sessions? This cannot be undone.`);
    if (!ok) return;

    setClearingHistory(true);
    try {
      const ids = analysisHistory.map((h) => h.id).filter(Boolean);
      await Promise.allSettled(ids.map((id) => deleteAnalysisById(id)));

      const currentGone = ids.includes(currentSessionId) || ids.includes(sessionId);
      if (currentGone) {
        clearLastSessionId();
        setSessionId(null);
        setCurrentSessionId(null);
        setAnalysisResult(null);
        setMessages([]);
        setView('intake');
      }

      await fetchSessions();
      showToast('History cleared', 'success');
    } catch (error) {
      console.error('[handleClearHistory] failed', error);
      showToast('Failed to clear history', 'error');
    } finally {
      setClearingHistory(false);
    }
  };

  // Persist a scenario row to the backend, then refresh bundle
async function persistScenario(label, values) {
  try {
    const apiBase = API_BASE;
    const threadId = currentSessionId || sessionId;
    if (!threadId || !analysisResult?.analysis_id) {
      throw new Error('Missing thread/analysis id');
    }

    const token = localStorage.getItem('access_token') || localStorage.getItem('token');
    const res = await fetch(
      `${apiBase}/api/market-iq/threads/${encodeURIComponent(threadId)}/scenarios`,
      {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
        body: JSON.stringify({
based_on: analysisResult?.analysis_id || sessionId,
          deltas: values || {},
          label: label || 'Scenario',
        }),
      }
    );

    const json = await res.json().catch(() => ({}));
    if (!res.ok) {
      const err = json?.error || `HTTP ${res.status}`;
      throw new Error(err);
    }

    // refresh bundle so the new scenario appears immediately
    await refreshBundle(threadId);
    return json?.scenario_id || null;
  } catch (e) {
    console.error('[persistScenario] failed', e);
    return null;
  }
}

// Capture scenario results so the Score dropdown can switch among them
const ensureVariantOption = (id, label, result) => {
  setScoreVariants(prev => {
    const exists = prev.some(v => v.id === id);
    if (exists) return prev.map(v => (v.id === id ? { ...v, result } : v));
    return [...prev, { id, label, result }];
  });
};

const handleScenarioResultA = (result) => {
  if (!result) return;
  setResultA(result);
  ensureVariantOption('scenarioA', 'Scenario A', result);
};

const handleScenarioResultB = (result) => {
  if (!result) return;
  setResultB(result);
  ensureVariantOption('scenarioB', 'Scenario B', result);
};

const handleScenarioResultC = (result) => {
  if (!result) return;
  setResultC(result);
  ensureVariantOption('scenarioC', 'Scenario C', result);
};

  // === Scenario Handling ===
const handleScenarioUpdate = async (newAnalysis) => {
  if (!newAnalysis) return;

  // Update UI immediately
  setAnalysisResult(newAnalysis);
  setActiveTab('summary');
  setView('summary');

  // REMOVED - AI Agent backend handles persistence automatically
  // try { await saveSessionToBackend({...}); } catch (e) { ... }

  // Pull fresh bundle so Scenarios list & latest analysis stay in sync
  try {
    await refreshBundle(currentSessionId || sessionId);
  } catch (e) {
    console.debug('[handleScenarioUpdate] refreshBundle failed', e);
  }

  // Refresh server history as the source of truth
  await fetchSessions();
};

const handleSaveScenario = async (scenario) => {
  const label  = scenario?.label || 'Scenario';
  const deltas = scenario?.values || scenario?.changes || {};

  // optimistic add
  const tempId = `scenario_${Date.now()}`;
  setSavedScenarios(prev => [...prev, { ...scenario, id: tempId }]);

  // persist to backend + refresh bundle
  const persistedId = await persistScenario(label, deltas);

  // reconcile temp id with real id (if we got one)
  if (persistedId) {
    setSavedScenarios(prev =>
      prev.map(s => (s.id === tempId ? { ...s, id: persistedId } : s))
    );
  }
};

  const handleCompareScenarios = async () => {
    await refreshBundle(currentSessionId || sessionId);
    setView('comparison');
    setActiveTab('scenario');
  };

  // === Help Chat ===
  const sendHelpMessage = async () => {
    if (!helpInput.trim() || helpLoading) return;

    const userMessage = { role: 'user', content: helpInput };
    setHelpMessages([...helpMessages, userMessage]);
    setHelpInput('');
    setHelpLoading(true);

    try {
      const token = localStorage.getItem('token');
      const response = await fetch(`${API_BASE}/api/help/chat`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          message: helpInput,
          context: 'Jaspen'
        })
      });
      const data = await response.json();

      if (data.success) {
        const assistantMessage = {
          role: 'assistant',
          content: data.response
        };
        setHelpMessages(prev => [...prev, assistantMessage]);
      }
    } catch (error) {
      console.error('Error sending help message:', error);
      const errorMessage = { role: 'assistant', content: 'Sorry, I encountered an error. Please try again.' };
      setHelpMessages(prev => [...prev, errorMessage]);
    } finally {
      setHelpLoading(false);
    }
  };

  // Debug readiness state
  useEffect(() => {
    console.log('[JAS readiness debug]', {
      sessionId,
      uiReadiness,
      audit_percent: readinessAudit?.overall?.percent,
    });
  }, [sessionId, uiReadiness, readinessAudit]);


  // =========================
  // ====== WORKSPACE TABS ===
  // =========================

  const buildScoreCommentary = (msgs = []) => {
    const aiMessages = [...msgs]
      .filter((m) => m?.role === 'ai' && (m?.text || '').trim())
      .slice(-3);
    if (aiMessages.length === 0) return null;

    const text = aiMessages.map((m) => m.text || '').join(' ').trim();
    if (!text) return null;

    const sentences = text
      .split(/(?<=[.!?])\s+/)
      .map((s) => s.trim())
      .filter(Boolean);

    const pick = (keywords) =>
      sentences.find((s) => keywords.some((k) => s.toLowerCase().includes(k))) || '';

    return {
      overall: sentences.slice(0, 2).join(' '),
      byCategory: {
        financial_health: pick(['financial', 'cash', 'revenue', 'margin', 'unit economics', 'profit', 'ebitda', 'ltv', 'cac']),
        market_position: pick(['market', 'position', 'competition', 'demand', 'segments', 'differentiation', 'gtm', 'go-to-market']),
        operational_efficiency: pick(['operations', 'efficiency', 'process', 'cost', 'execution', 'scale', 'throughput']),
        execution_readiness: pick(['execution', 'readiness', 'team', 'timeline', 'plan', 'resources', 'milestone']),
      },
      source: 'chat_transcript_latest_ai',
    };
  };

  const scoreCommentary = useMemo(() => buildScoreCommentary(messages), [messages]);

  const renderWorkspaceShell = () => {
    const isReadinessOpen = activeTab === 'chat' && sidebarState.readiness;
    const isSettingsOpen = sidebarState.settings;
    const isScenarioTab = activeTab === 'scenario';
    const shellOpen = sidebarState.history || sidebarState.readiness || sidebarState.settings;
    const sideTabBase = 128;
    const sideTabGap = 130;
    const sideTabSecond = sideTabBase + sideTabGap;
    const workspaceProjectTitle = deriveIdeaTitle({
      result: activeScorecard || analysisResult,
      messages,
      fallback: 'Untitled Idea',
    });
    const snapshotOptions = Array.isArray(scorecardSnapshots)
      ? [...scorecardSnapshots]
          .sort((a, b) => {
            if (Boolean(a?.isBaseline) !== Boolean(b?.isBaseline)) {
              return a?.isBaseline ? -1 : 1;
            }
            return Number(a?.createdAt || 0) - Number(b?.createdAt || 0);
          })
          .map((snap, idx) => ({
            id: snap.id,
            label: snap.isBaseline ? 'Baseline' : (snap.label || `Scenario ${idx}`),
          }))
      : [];
    const useSnapshotSelect = snapshotOptions.length > 0;
    const scoreSelectValue = useSnapshotSelect
      ? (selectedScorecardId || snapshotOptions[0]?.id || '')
      : selectedVariantId;
    const TabButton = ({ id, label }) => (
      <button
        className={`jas-top-tab ${activeTab === id ? 'active' : ''}`}
        role="tab"
        aria-selected={activeTab === id}
onClick={async () => {
  setActiveTab(id);
setView(id === 'chat' ? 'intake' : id);

  // If the user opens the Scenarios tab, pull the latest bundle from the backend
  if (id === 'scenario' && (sessionId || analysisResult?.analysis_id)) {
    try {
      const tid = sessionId || analysisResult?.analysis_id;
      await refreshBundle(tid);
    } catch {}
  }
}}
      >
        {label}
      </button>
    );

    if (process.env.NODE_ENV === "development" && activeTab === 'summary') {
      const activeAnalysis = activeScorecard;
      console.log('[ScoreDashboard activeAnalysis]', {
        activeAnalysisName: 'activeScorecard',
        activeAnalysisKeys: Object.keys(activeAnalysis || {}),
        scoresKeys: Object.keys(activeAnalysis?.scores || {}),
        financialImpactKeys: Object.keys(activeAnalysis?.financial_impact || {}),
        sections: {
          decision_framework: Boolean(activeAnalysis?.decision_framework),
          investment_analysis: Boolean(activeAnalysis?.investment_analysis),
          npv_irr_analysis: Boolean(activeAnalysis?.npv_irr_analysis),
          valuation: Boolean(activeAnalysis?.valuation),
          before_after_financials: Boolean(activeAnalysis?.before_after_financials),
          metrics: Boolean(activeAnalysis?.metrics),
        },
      });
    }

    return (
      <div className={`jas jas-shell ${shellOpen ? 'drawer-open' : ''}`}>
        <main className="jas-main">
          <ToastContainer toasts={toasts} onDismiss={dismissToast} />

{activeTab === 'chat' && (
  <>
    {/* LEFT SIDEBAR - Readiness (only on Refine & Rescore tab) */}
    <div className={`jas-left-sidebar jas-readiness-sidebar ${sidebarState.readiness ? 'sidebar-open' : ''}`}>
      <div className="jas-sidebar-header">
        <h3>Analysis Readiness</h3>
        <button className="jas-sidebar-close" onClick={() => dispatchSidebar({ type: 'CLOSE_READINESS' })}>
          <FontAwesomeIcon icon={faTimes} />
        </button>
      </div>
      <div className="jas-sidebar-content">
        <div className="jas-readiness-display">
          <div className="jas-readiness-circle">
            <svg className="jas-progress-ring" width="120" height="120">
              <circle className="jas-progress-ring-bg" stroke="#e2e8f0" strokeWidth="8" fill="transparent" r="52" cx="60" cy="60" />
              <circle
                className="jas-progress-ring-fill"
                stroke="#10b981"
                strokeWidth="8"
                fill="transparent"
                r="52"
                cx="60" cy="60"
                strokeDasharray={`${(uiReadiness / 100) * READINESS_CIRC} ${READINESS_CIRC}`}
                strokeDashoffset="0"
                transform="rotate(-90 60 60)"
              />
            </svg>
            <div className="jas-readiness-percent">{Math.round(uiReadiness)}%</div>
          </div>
          <div className="jas-readiness-status">
            {uiReadiness < 60 ? 'Gathering information...' : uiReadiness < 90 ? 'Almost ready!' : 'Ready to analyze!'}
          </div>
        </div>

        <div className="jas-collected-section">
          <h4>Information Categories</h4>
          <div className="jas-checklist">
            {(readinessAudit?.categories || []).map((category) => {
              const key = category.key;
              const label = category.label || specMap[key]?.label || key;
              const done = category.completed === true;
              const weightPct = (Number(category.weight || 0) * 100).toFixed(0);

              return (
                <div key={key} className={`jas-check-item ${done ? 'is-done' : ''}`}>
                  <input type="checkbox" className="jas-check" checked={done} readOnly />
                  <div className="jas-check-main">
                    <div className="jas-check-label">{label}</div>
                    <div className="jas-check-meta">
                      <span className="jas-check-weight">{weightPct}% weight</span>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>
      {renderSidebarFooter(() => dispatchSidebar({ type: 'CLOSE_READINESS' }))}
    </div>

    {sessionId && messages.length > 0 && !sidebarState.readiness && (
      <div
        className="jas-sidebar-tab jas-tab-readiness"
        style={{ top: `${sideTabSecond}px` }}
        onClick={() => dispatchSidebar({ type: 'OPEN_READINESS' })}
      >
        <FontAwesomeIcon icon={faChartLine} />
        <span className="jas-tab-label">Readiness</span>
      </div>
    )}
  </>
)}

      {/* LEFT SIDEBAR - User Settings */}
      <div className={`jas-left-sidebar jas-settings-sidebar ${sidebarState.settings ? 'sidebar-open' : ''}`}>
        <div className="jas-sidebar-header">
          <h3>User Settings</h3>
          <button className="jas-sidebar-close" onClick={() => dispatchSidebar({ type: 'CLOSE_SETTINGS' })}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          {renderUserMenuContent(() => dispatchSidebar({ type: 'CLOSE_SETTINGS' }))}
        </div>
      </div>

      {!sidebarState.settings && (
        <div
          className="jas-sidebar-tab jas-tab-settings"
          onClick={() => dispatchSidebar({ type: 'TOGGLE_SETTINGS' })}
          role="button"
          aria-label="User settings"
          title="User settings"
          style={{ top: `${sideTabBase}px` }}
        >
          <FontAwesomeIcon icon={faBars} />
          <span className="jas-tab-label">Menu</span>
        </div>
      )}

      {busy && (
        <div className="thinking-overlay">
          <div className="thinking-content">
            <FontAwesomeIcon icon={faSpinner} spin />
            <span>Thinking...</span>
          </div>
        </div>
      )}

      {renderNameModal()}
      {renderBillingModal()}

{/* Assistant Vertical Tab (Score + Scenarios only) */}
{activeTab !== 'chat' && !aiDrawerOpen && (
  <div
    className="jas-sidebar-tab jas-tab-assistant"
    style={{ top: `${sideTabSecond}px` }}
    onClick={toggleAIDrawer}
    role="button"
    aria-label="Jaspen"
    title="Jaspen"
  >
    <span className="jas-tab-label">Jaspen</span>
  </div>
)}

{/* Assistant Drawer (Score + Scenarios only) */}
{activeTab !== 'chat' && (
  <div className={`jas-ai-drawer ${aiDrawerOpen ? 'jas-drawer-open' : ''}`}>
    <div className="jas-ai-header">
      <div className="jas-ai-title">
        <span>{isScenarioTab && scenarioDrawerView === 'scorecard' ? 'Score Summary' : 'Jaspen'}</span>
      </div>
      <button className="jas-close-btn" onClick={toggleAIDrawer}>
        <FontAwesomeIcon icon={faTimes} />
      </button>
    </div>

    {isScenarioTab && (
      <div className="jas-ai-toggle">
        <button
          type="button"
          className={`jas-ai-toggle-btn ${scenarioDrawerView === 'assistant' ? 'active' : ''}`}
          onClick={() => setScenarioDrawerView('assistant')}
        >
          Jaspen
        </button>
        <button
          type="button"
          className={`jas-ai-toggle-btn ${scenarioDrawerView === 'scorecard' ? 'active' : ''}`}
          onClick={() => setScenarioDrawerView('scorecard')}
        >
          Score Summary
        </button>
      </div>
    )}

    {(!isScenarioTab || scenarioDrawerView === 'assistant') ? (
      <>
        <div className="jas-ai-messages">
          {messages.map((m, idx) => (
            <div
              key={idx}
              className={`jas-ai-message ${m.role === 'user' ? 'user' : 'assistant'}`}
            >
              <div className="jas-message-content">{m.text || ''}</div>
            </div>
          ))}
        </div>

        <div className="jas-ai-input-area">
          <textarea
            className="jas-ai-input"
            placeholder="Ask about tasks, timeline, resources..."
            rows="3"
            value={aiInput}
            onChange={(e) => setAiInput(e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendAIMessage();
              }
            }}
          />
          <button className="jas-ai-send-btn" onClick={sendAIMessage}>
            <FontAwesomeIcon icon={faPaperPlane} />
          </button>
        </div>
      </>
    ) : (
      <div className="jas-ai-messages">
        {renderMiniScorecard(activeScorecard)}
      </div>
    )}
    {renderSidebarFooter(() => setAiDrawerOpen(false))}
  </div>
)}

{/* Refine & Rescore shows only the readiness sidebar (no assistant drawer). */}

      <ThreadEditModal
        open={threadEditOpen}
        onClose={() => setThreadEditOpen(false)}
        sessionId={sessionId}
        threadId={sessionId}
        initialName={analysisResult?.project_name || ''}
        initialAdoptedAnalysisId={analysisResult?.analysis_id || ''}
        authFetch={authFetch}
        onSaved={(payload) => {
          if (payload?.name) {
            setAnalysisResult((prev) => prev ? { ...prev, project_name: payload.name } : prev);
          }
          refreshBundle(sessionId);
        }}
      />

        <div className={`jas-workspace ${aiDrawerOpen ? 'jas-ai-open' : ''} ${isReadinessOpen ? 'jas-readiness-open' : ''} ${isSettingsOpen ? 'jas-settings-open' : ''}`}>
          <div className="jas-workspace-header">
            <div className="jas-workspace-title">
              <h2 className="jas-project-title">
                {workspaceProjectTitle}
              </h2>
            </div>

            <nav className="jas-top-tabs" role="tablist" aria-label="Jaspen views">
              <TabButton id="summary"  label="Score" />
              <TabButton id="scenario" label="Scenarios" />
              <TabButton id="chat"     label="Refine & Rescore" />

              {/* Only show dropdowns and Begin Project on Score tab */}
              {activeTab === 'summary' && (
                <div className="jas-right-rail">
                  <select
                    className="jas-variant-select"
                    aria-label="Score View"
                    value={scoreSelectValue}
                    onChange={(e) => {
                      const next = e.target.value;
                      if (useSnapshotSelect) {
                        setSelectedScorecardId(next);
                        return;
                      }
                      setSelectedVariantId(next);
                    }}
                  >
                    {useSnapshotSelect
                      ? snapshotOptions.map((opt) => (
                          <option key={opt.id} value={opt.id}>{opt.label}</option>
                        ))
                      : scoreVariants.map((v) => (
                          <option key={v.id} value={v.id}>{v.label}</option>
                        ))}
                  </select>

                  <select
                    className="jas-scores-select"
                    aria-label="Completed Scores"
                    onChange={(e) => {
                      const sel = analysisHistory.find(s => s.id === e.target.value);
                      if (sel?.result) handleSelectAnalysis(sel.result);
                    }}
                  >
                    <option value="">Completed Scores</option>
                    {analysisHistory
                      .filter(s => (s.result?.status || 'completed') === 'completed')
                      .map(s => (
                        <option key={s.id} value={s.id}>
                          {(s.result?.project_name || 'Analysis').slice(0, 32)}
                          {s.result?.market_iq_score != null ? ` — ${s.result.market_iq_score}` : ''}
                        </option>
                      ))}
                  </select>

                  <button
                    className="begin-project-btn"
                    onClick={onBeginProject}
                    disabled={beginBusy}
                  >
                    <FontAwesomeIcon icon={beginBusy ? faSpinner : faPlay} spin={beginBusy} />
                    <span>{beginBusy ? "Working…" : "Begin Project"}</span>
                  </button>
                </div>
              )}

{/* ===== BEGIN: Begin Project overlay (fixed) ===== */}
{beginBusy && (
  <div
    style={{
      position: "fixed",
      inset: 0,
      background: "rgba(15, 23, 42, 0.55)",
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      zIndex: 9999,
      backdropFilter: "blur(2px)",
    }}
    aria-live="polite"
  >
    <div
      style={{
        background: "white",
        borderRadius: 12,
        padding: "20px 24px",
        minWidth: 280,
        boxShadow: "0 10px 30px rgba(0,0,0,.15)",
        textAlign: "center",
      }}
    >
      <div style={{ fontSize: 22, marginBottom: 10, fontWeight: 600, color: "#0f172a" }}>
        Getting Things Ready
      </div>
      <div style={{ marginBottom: 14, color: "#334155" }}>{beginMsg}</div>
      <div style={{ display: "flex", gap: 6, justifyContent: "center" }}>
        {[0,1,2].map((i) => (
          <span
            key={i}
            style={{
              width: 8,
              height: 8,
              borderRadius: "50%",
              background: "#8b5cf6",
              display: "inline-block",
              animation: `jas-dot 1s ease-in-out ${i * 0.12}s infinite`,
            }}
          />
        ))}
      </div>
      <style>{`
        @keyframes jas-dot {
          0%, 80%, 100% { transform: translateY(0); opacity: .6; }
          40% { transform: translateY(-6px); opacity: 1; }
        }
      `}</style>
    </div>
  </div>
)}
{/* ===== END: Begin Project overlay ===== */}
            </nav>
          </div>

          <div className="jas-workspace-body">
{activeTab === 'summary' && (
  <div className={!sidebarState.settings || !aiDrawerOpen ? 'score-with-rail' : ''}>
    <ScoreDashboard
      analysisResult={activeScorecard}

      scoreVariants={scoreVariants}
      selectedVariantId={selectedVariantId}
      onSelectVariant={setSelectedVariantId}

      scorecardSnapshots={scorecardSnapshots}
      selectedScorecardId={selectedScorecardId}
      onSelectScorecard={setSelectedScorecardId}
      baselineScorecardId={baselineScorecardId}
      threadBundleId={sessionId}
      scoreCommentary={scoreCommentary}
      onOpenThreadEdit={() => setThreadEditOpen(true)}

      onBackToMain={handleNewAnalysis}
      onOpenChat={() => { setActiveTab('chat'); setView('intake'); }}
      onOpenScenario={() => { setActiveTab('scenario'); setView('scenario'); }}
      onConvertToProject={() => {
        storage.saveProject({
          id: `proj_${Date.now()}`,
          source_analysis_id: sessionId,
          createdAt: Date.now(),
          title: deriveIdeaTitle({ result: analysisResult, messages, fallback: 'Untitled Idea' }),
          payload: analysisResult,
        });
        window.location.href = `https://sekki.io/ops/project-planning?from=jas&analysis=${encodeURIComponent(sessionId)}`;
      }}
    />
  </div>
)}

            {activeTab === 'chat' && (
              <div className="jas-chat-tab">
                <div className="chatgpt-content">
                  <div className="chatgpt-messages">
                    {error && (
                      <div className="chatgpt-error">
                        <FontAwesomeIcon icon={faExclamationTriangle} />
                        <span>{error}</span>
                      </div>
                    )}

                    <div className="chatgpt-conversation">
                      {messages.map((m, idx) => (
                        <div key={idx} className={`chatgpt-message ${m.role === 'ai' ? 'ai' : 'user'}`}>
                          <div className="message-content">{m.text}</div>

                          {Array.isArray(m.attachments) && m.attachments.length > 0 && (
                            <div className="message-attachments">
                              {m.attachments.map((a, i) => (
                                <div key={i} className="message-attachment">
                                  {a.preview && a.type?.startsWith?.('image/')
                                    ? (
                                      <img
                                        className="attachment-thumb"
                                        src={a.preview}
                                        alt={a.name}
                                        onLoad={() => {
                                          try { if (a.preview) URL.revokeObjectURL(a.preview); } catch {}
                                        }}
                                      />
                                    )
                                    : (
                                      <a
                                        className="attachment-link"
                                        href={a.preview || '#'}
                                        onClick={(e) => { if (!a.preview) e.preventDefault(); }}
                                        download={a.name}
                                        title={a.name}
                                      >
                                        {a.name}
                                      </a>
                                    )
                                  }
                                  <span className="attachment-meta">
                                    {Math.round((a.size || 0) / 1024)} KB
                                  </span>
                                </div>
                              ))}

                              <div className="attachments-caption">
                                Attached {m.attachments.length} {m.attachments.length === 1 ? 'file' : 'files'}
                              </div>
                            </div>
                          )}
                        </div>
                      ))}
                      <div ref={endRef} />
                    </div>
                  </div>

                  <div className="chatgpt-input-area">
                    <div className="chatgpt-input-container">
                      <button
                        type="button"
                        className="chatgpt-plus"
                        aria-label="Attach files"
                        title="Attach files"
                        disabled={busy}
                        onClick={() => fileInputRef.current?.click()}
                      >
                        <FontAwesomeIcon icon={faPlus} />
                      </button>

                      <input
                        ref={fileInputRef}
                        id="jas-file-input"
                        type="file"
                        multiple
                        accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.txt,.md"
                        onChange={onFilesSelected}
                        style={{ display: 'none' }}
                      />

                      {pendingFiles?.length > 0 && (
                        <div className="jas-file-chips">
                          {pendingFiles.map((f, i) => (
                            <span key={i} className="jas-file-chip">
                              {f.name}
                              <button
                                type="button"
                                className="jas-file-chip-remove"
                                title="Remove"
                                onClick={() =>
                                  setPendingFiles(prev => prev.filter((_, idx) => idx !== i))
                                }
                              >
                                ×
                              </button>
                            </span>
                          ))}
                        </div>
                      )}

                      <textarea
                        value={input}
                        onChange={(e)=>setInput(e.target.value)}
                        onKeyDown={onKey}
                        placeholder="Refine the conversation to improve your scorecard..."
                        className="chatgpt-input"
                        rows={1}
                        disabled={busy}
                      />

                      <button
                        type="button"
                        className={`chatgpt-mic ${isRecording ? 'is-recording' : ''}`}
                        aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                        aria-pressed={isRecording}
                        title={isRecording ? 'Stop recording' : 'Start recording'}
                        disabled={busy}
                        onClick={() => setIsRecording(prev => !prev)}
                      >
                        <FontAwesomeIcon icon={faMicrophone} />
                      </button>

                      <button
                        className="chatgpt-send"
                        onClick={onSubmit}
                        disabled={busy || (!input.trim() && pendingFiles.length === 0)}
                        title="Send"
                      >
                        {busy ? <FontAwesomeIcon icon={faSpinner} spin /> : <FontAwesomeIcon icon={faPaperPlane} />}
                      </button>
                    </div>

                    {sessionId && hasConversationMessages && (
                      <div className="chatgpt-footer">
                        <div className="progress-indicator">
                          <div className="progress-bar-container">
                            <div className="progress-bar-fill" style={{ width: `${uiReadiness}%` }}></div>
                          </div>
                          <span className="progress-text">{Math.round(uiReadiness)}% ready</span>
                        </div>
                        <button
                          className="finish-analyze-btn"
                          onClick={onFinishAnalyze}
                          disabled={!canAnalyze || busy}
                          title={canAnalyze ? "Regenerate your Jaspen score" : "Keep chatting to gather more information"}
                        >
                          <FontAwesomeIcon icon={faCheck} />
                          <span>Finish & Analyze</span>
                        </button>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            )}

            {activeTab === 'scenario' && (
              <>
                {view === 'comparison' && savedScenarios.length > 0 ? (
                  <ComparisonView
                    baseAnalysis={analysisResult}
                    scenarios={savedScenarios}
                    onBackToScenario={() => { setView('scenario'); }}
                    onBackToSummary={() => { setActiveTab('summary'); setView('summary'); }}
                    onAdopt={handleScenarioUpdate}
                  />
                ) : (
<ScenarioModeler
  ref={scenarioModelerRef}
  analysisId={sessionId}
  baseAnalysis={bundleBaselineScorecard || baselineRef.current || analysisResult}
  scenarioLevers={scenarioLevers}
  savedScenarios={savedScenarios}
  onAdoptScenario={handleScenarioAdopt}
  onAdoptScorecard={handleAdoptScorecard}
  onBackToSummary={() => { setActiveTab('summary'); setView('summary'); }}
  onOpenChat={() => { setActiveTab('chat'); setView('intake'); }}
  onAdopt={handleScenarioUpdate}
  onSaveScenario={handleSaveScenario}
  onCompare={handleCompareScenarios}
onResultA={(res) => { setResultA(res); setSelectedVariantId('scenarioA'); }}
onResultB={(res) => { setResultB(res); setSelectedVariantId('scenarioB'); }}
onResultC={(res) => { setResultC(res); setSelectedVariantId('scenarioC'); }}
  onConvertToProject={() => {
    storage.saveProject({
      id: `proj_${Date.now()}`,
      source_analysis_id: sessionId,
      createdAt: Date.now(),
      title: deriveIdeaTitle({ result: analysisResult, messages, fallback: 'Untitled Idea' }),
      payload: analysisResult,
    });
    window.location.href = `https://sekki.io/ops/project-planning?from=jas&analysis=${encodeURIComponent(sessionId)}`;
  }}
/>
                )}
              </>
            )}
          </div>
        </div>
        </main>
      </div>
    );
  };

  // =========================
  // ======== RENDERS ========
  // =========================

  // If we have an analysis, render the workspace with tabs (post-Analyze)
  if (analysisResult) {
    return renderWorkspaceShell();
  }

  // Default: conversational intake (no tabs)
  const intakeShellOpen = sidebarState.history || sidebarState.readiness || sidebarState.settings;
  const intakeHasReadinessTab = sessionId && messages.length > 0 && !sidebarState.readiness;
  const intakeTabs = [];
  if (!sidebarState.settings) intakeTabs.push('settings');
  if (hasHistory && !sidebarState.history) intakeTabs.push('history');
  if (intakeHasReadinessTab) intakeTabs.push('readiness');
  const intakeTabTop = (key) => {
    const idx = intakeTabs.indexOf(key);
    return `${128 + idx * 130}px`;
  };
  return (
    <div className={`jas jas-shell ${intakeShellOpen ? 'drawer-open' : ''}`}>
      <main className="jas-main">
        <div className="chatgpt-interface">
      {busy && (
        <div className="thinking-overlay">
          <div className="thinking-content">
            <FontAwesomeIcon icon={faSpinner} spin />
            <span>{sessionId ? "Thinking..." : "Starting conversation..."}</span>
          </div>
        </div>
      )}

      {/* Drawer Tabs on Left Edge */}
      {!sidebarState.settings && (
        <div
          className="jas-drawer-tab jas-drawer-tab-settings"
          style={{ top: intakeTabTop('settings') }}
          onClick={() => dispatchSidebar({ type: 'TOGGLE_SETTINGS' })}
        >
          <FontAwesomeIcon icon={faBars} />
          MENU
        </div>
      )}
      {hasHistory && !sidebarState.history && (
        <div
          className="jas-drawer-tab jas-drawer-tab-history"
          style={{ top: intakeTabTop('history') }}
          onClick={() => dispatchSidebar({ type: 'TOGGLE_HISTORY' })}
        >
          <FontAwesomeIcon icon={faClockRotateLeft} />
          HISTORY
        </div>
      )}
      {intakeHasReadinessTab && (
        <div
          className={`jas-drawer-tab jas-drawer-tab-readiness ${sessionId && messages.length > 0 ? 'active' : ''}`}
          style={{ top: intakeTabTop('readiness') }}
          onClick={() => dispatchSidebar({ type: 'OPEN_READINESS' })}
        >
          <FontAwesomeIcon icon={faGaugeHigh} />
          READINESS
        </div>
      )}

      {/* Drawer Overlay - non-blocking, just visual dimming */}

      {/* LEFT SIDEBAR - Readiness */}
      <div className={`jas-left-sidebar jas-readiness-sidebar ${sidebarState.readiness ? 'sidebar-open' : ''}`}>
        <div className="jas-sidebar-header">
          <h3>Analysis Readiness</h3>
          <button className="jas-sidebar-close" onClick={() => dispatchSidebar({ type: 'CLOSE_READINESS' })}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          <div className="jas-readiness-display">
            <div className="jas-readiness-circle">
              <svg className="jas-progress-ring" width="120" height="120">
                <circle className="jas-progress-ring-bg" stroke="#e2e8f0" strokeWidth="8" fill="transparent" r="52" cx="60" cy="60" />
                <circle
                  className="jas-progress-ring-fill"
                  stroke="#10b981"
                  strokeWidth="8"
                  fill="transparent"
                  r="52"
                  cx="60" cy="60"
                  strokeDasharray={`${(uiReadiness / 100) * READINESS_CIRC} ${READINESS_CIRC}`}
                  strokeDashoffset="0"
                  transform="rotate(-90 60 60)"
                />
              </svg>
              <div className="jas-readiness-percent">{Math.round(uiReadiness)}%</div>
            </div>
<div className="jas-readiness-status">
  {uiReadiness < 60 ? 'Gathering information...' : uiReadiness < 90 ? 'Almost ready!' : 'Ready to analyze!'}
</div>

{(readinessSource || readinessVersion) && (
  <div className="jas-readiness-meta" style={{ marginTop: '6px', fontSize: '12px', color: '#64748b' }}>
    {readinessSource && (
      <span className="jas-chip" style={{
        display: 'inline-block', padding: '2px 6px', borderRadius: '8px',
        border: '1px solid #cbd5e1', marginRight: '6px'
      }}>
        Source: {readinessSource.toUpperCase()}
      </span>
    )}
    {readinessVersion && (
      <span className="jas-chip" style={{
        display: 'inline-block', padding: '2px 6px', borderRadius: '8px',
        border: '1px solid #cbd5e1'
      }}>
        {readinessVersion}
      </span>
    )}
  </div>
)}
          </div>

<div className="jas-collected-section">
  <h4>Information Categories</h4>

  <div className="jas-checklist">
    {(readinessAudit?.categories || []).map((category) => {
      // backend drives these; stay literal
      const key       = category.key;
      const label     = category.label || specMap[key]?.label || key;

const done = category.completed === true;
      const percent   = Math.max(0, Math.min(100, Math.round(Number(category.percent || 0))));
      const weightPct = (Number(category.weight || 0) * 100).toFixed(0); // e.g. "25"

      return (
        <div key={key} className={`jas-check-item ${done ? 'is-done' : ''}`}>
          <input
            type="checkbox"
            className="jas-check"
            checked={done}
            readOnly
            aria-label={label}
            title={done ? 'Complete' : 'Not complete'}
          />
          <div className="jas-check-main">
            <div className="jas-check-label">{label}</div>
            <div className="jas-check-meta">
              {/* show what the backend said, but keep it subtle */}
              <span className="jas-check-weight">{weightPct}% weight</span>
            </div>
          </div>
        </div>
      );
    })}
  </div>
</div>
        </div>
        {renderSidebarFooter(() => dispatchSidebar({ type: 'CLOSE_READINESS' }))}
      </div>

      {/* LEFT SIDEBAR - History */}
      {hasHistory && (
        <div className={`jas-left-sidebar jas-history-sidebar ${sidebarState.history ? 'sidebar-open' : ''}`}>
          <div className="jas-sidebar-header">
            <h3>Analysis History</h3>
            <div className="jas-sidebar-header-actions">
              <button
                className="jas-sidebar-clear"
                onClick={handleClearHistory}
                disabled={clearingHistory || analysisHistory.length === 0}
                title="Clear all history"
              >
                {clearingHistory ? 'Clearing…' : 'Clear'}
              </button>
              <button className="jas-sidebar-close" onClick={() => dispatchSidebar({ type: 'CLOSE_HISTORY' })}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>
          </div>
          <div className="jas-sidebar-content">
            {analysisHistory.map((item, index) => (
              <div key={index} className="jas-history-item" onClick={() => handleSelectAnalysis(item.result)}>
                <div className="hi-text">
                  <div className="hi-title">
                    {item.result?.project_name || `Analysis ${item.id?.slice(-8) || index + 1}`}
                  </div>
                  <div className="hi-meta">
                    <span>{new Date(item.createdAt).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
                    {item.result?.market_iq_score && (<span className="hi-score">Score: {item.result.market_iq_score}</span>)}
                  </div>
                </div>
                <button
                  className="hi-delete"
                  onClick={(e) => {
                    e.stopPropagation();
                    handleDeleteAnalysis(item.id);
                  }}
                  title="Delete"
                >
                  <FontAwesomeIcon icon={faTrash} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LEFT SIDEBAR - User Settings */}
      <div className={`jas-left-sidebar jas-settings-sidebar ${sidebarState.settings ? 'sidebar-open' : ''}`}>
        <div className="jas-sidebar-header">
          <h3>User Settings</h3>
          <button className="jas-sidebar-close" onClick={() => dispatchSidebar({ type: 'CLOSE_SETTINGS' })}>
            <FontAwesomeIcon icon={faTimes} />
          </button>
        </div>
        <div className="jas-sidebar-content">
          {renderUserMenuContent(() => dispatchSidebar({ type: 'CLOSE_SETTINGS' }))}
        </div>
      </div>

      {/* Header - Manus Style Top Bar */}
      <div className="jas-chat-topbar">
        <div className="jas-topbar-left">
          <button
            type="button"
            className="jas-topbar-title jas-topbar-link"
            onClick={() => window.location.reload()}
            title="Refresh"
          >
            Jaspen
          </button>
          <button
            className="jas-topbar-new"
            onClick={() => handleNewAnalysis(true)}
            title="New Session"
            aria-label="New Session"
          >
            <FontAwesomeIcon icon={faPlus} />
          </button>
        </div>

        <div className="jas-topbar-right" />
      </div>

      {renderNameModal()}
      {renderBillingModal()}

      {/* Content */}
      <div className="jas-chat-content">
        {messages.length === 0 ? (
          <div className="jas-chat-welcome">
            <h2 className="jas-chat-welcome-title">
              <img
                className="jas-chat-welcome-unicorn"
                src="/android-chrome-192x192.png"
                alt="Jaspen unicorn"
              />
              <span>{welcomeHeading}</span>
            </h2>
            <p>Describe your project or business idea and I'll help you build a complete strategy scorecard through a natural conversation.</p>
          </div>
        ) : (
          <div className="jas-messages">
            {error && (
              <div className="chatgpt-error">
                <FontAwesomeIcon icon={faExclamationTriangle} />
                <span>{error}</span>
              </div>
            )}

            {messages.map((m, idx) => (
              <div key={idx} className={`jas-message ${m.role === 'ai' ? 'ai' : 'user'}`}>
                <div className="jas-message-bubble">{m.text}</div>
              </div>
            ))}

            <div ref={endRef} />
          </div>
        )}

        {/* Input Area - Manus Style */}
        <div className="jas-chat-input-area">
          <input
            ref={fileInputRef}
            id="jas-file-input"
            type="file"
            multiple
            accept="image/*,.pdf,.doc,.docx,.ppt,.pptx,.xls,.xlsx,.csv,.txt,.md"
            onChange={onFilesSelected}
            style={{ display: 'none' }}
          />

          {pendingFiles?.length > 0 && (
            <div className="jas-file-chips" style={{ maxWidth: '800px', margin: '0 auto 8px', display: 'flex', flexWrap: 'wrap', gap: '4px' }}>
              {pendingFiles.map((f, i) => (
                <span key={i} style={{ display: 'inline-flex', alignItems: 'center', gap: '4px', padding: '4px 8px', background: '#f1f3f5', borderRadius: '4px', fontSize: '0.75rem' }}>
                  {f.name}
                  <button
                    type="button"
                    style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0', fontSize: '0.875rem', color: '#868e96' }}
                    title="Remove"
                    onClick={() => setPendingFiles(prev => prev.filter((_, idx) => idx !== i))}
                  >
                    ×
                  </button>
                </span>
              ))}
            </div>
          )}

          <div className="jas-chat-input-box">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={onKey}
              placeholder={sessionId ? "Continue the conversation..." : "Describe your project or goal..."}
              rows={1}
              disabled={busy}
            />
            <div className="jas-chat-input-icons">
              <button
                type="button"
                className="jas-ci-btn"
                aria-label="Attach files"
                title="Attach"
                disabled={busy}
                onClick={() => fileInputRef.current?.click()}
              >
                <FontAwesomeIcon icon={faPaperclip} />
              </button>
              <button
                type="button"
                className={`jas-ci-btn ${isRecording ? 'recording' : ''}`}
                aria-label={isRecording ? 'Stop recording' : 'Start recording'}
                title="Voice"
                disabled={busy}
                onClick={() => setIsRecording(prev => !prev)}
              >
                <FontAwesomeIcon icon={faMicrophone} />
              </button>
              <button
                className="jas-ci-btn send"
                onClick={onSubmit}
                disabled={busy || (!input.trim() && pendingFiles.length === 0)}
                title="Send"
              >
                {busy ? <FontAwesomeIcon icon={faSpinner} spin /> : <FontAwesomeIcon icon={faArrowUp} />}
              </button>
            </div>
          </div>

          {sessionId && hasConversationMessages && (
            <div className="chatgpt-footer">
              <div className="progress-indicator">
                <div className="progress-bar-container">
                  <div className="progress-bar-fill" style={{ width: `${uiReadiness}%` }}></div>
                </div>
                <span className="progress-text">{Math.round(uiReadiness)}% ready</span>
              </div>
              <button
                className="finish-analyze-btn"
                onClick={onFinishAnalyze}
                disabled={!canAnalyze || busy}
                title={canAnalyze ? "Generate your Jaspen score" : "Keep chatting to gather more information"}
              >
                <FontAwesomeIcon icon={faCheck} />
                <span>Finish & Analyze</span>
              </button>
            </div>
          )}
        </div>
      </div>

      {/* Help Modal */}
      {helpOpen && (
        <div className="jas-help-modal">
          <div className="jas-help-content">
            <div className="jas-help-header">
              <h3>Help & Support</h3>
              <button className="jas-help-close" onClick={() => setHelpOpen(false)}>
                <FontAwesomeIcon icon={faTimes} />
              </button>
            </div>

            <div className="jas-help-messages">
              {helpMessages.length === 0 ? (
                <div className="jas-help-welcome">
                  <p>Hi! I'm here to help you with:</p>
                  <ul>
                    <li>Understanding Jaspen features</li>
                    <li>Navigating the platform</li>
                    <li>Project management tools</li>
                    <li>Lean Six Sigma resources</li>
                  </ul>
                  <p>What can I help you with?</p>
                </div>
              ) : (
                helpMessages.map((msg, idx) => (
                  <div key={idx} className={`jas-help-message ${msg.role}`}>
                    <div className="jas-help-bubble">
                      {msg.role === 'user' ? (
                        msg.content
                      ) : (
                        <div
                          dangerouslySetInnerHTML={{
                            __html: msg.content
                              .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                              .replace(/^## (.+)$/gm, '<h4>$1</h4>')
                              .replace(/^### (.+)$/gm, '<h5>$1</h5>')
                              .replace(/^- (.+)$/gm, '<li>$1</li>')
                              .replace(/(<li>[\s\S]*?<\/li>(\n|$))+/g, '<ul>$&</ul>')
                              .replace(/\n\n/g, '<br/><br/>')
                              .replace(/\n/g, '<br/>')
                          }}
                        />
                      )}
                    </div>
                  </div>
                ))
              )}
              {helpLoading && (
                <div className="jas-help-loading">
                  <span>Thinking...</span>
                </div>
              )}
            </div>

            <div className="jas-help-input">
              <textarea
                value={helpInput}
                onChange={(e) => setHelpInput(e.target.value)}
                onKeyPress={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault();
                    sendHelpMessage();
                  }
                }}
                placeholder="Ask a question..."
                disabled={helpLoading}
              />
              <button onClick={sendHelpMessage} disabled={helpLoading || !helpInput.trim()}>
                <FontAwesomeIcon icon={faPaperPlane} />
              </button>
            </div>
          </div>
        </div>
      )}
        </div>
      </main>
    </div>
  );
}
